"""Staged lifecycle, durable worker, and runtime wiring tests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.knowledge import (
    IKnowledgeGateway,
    KnowledgeGatewayWriteResult,
    KnowledgeIndexDocument,
    KnowledgeSearchHit,
    KnowledgeSearchQuery,
    KnowledgeSearchResult,
)
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.knowledge_pack.api.validation import (
    KnowledgePackArchiveValidation,
    KnowledgePackPublishValidation,
    KnowledgePackReindexValidation,
    KnowledgePackRollbackVersionValidation,
)
from mugen.core.plugin.knowledge_pack.domain import (
    KnowledgeIndexProjectionDE,
    KnowledgePackDE,
    KnowledgePackVersionDE,
)
from mugen.core.plugin.knowledge_pack.fw_ext import KnowledgePackFWExtension
from mugen.core.plugin.knowledge_pack.runtime import configure_knowledge_gateway
from mugen.core.plugin.knowledge_pack.service.knowledge_pack_version import (
    KnowledgePackVersionService,
)
from mugen.core.plugin.knowledge_pack.service.projection_worker import (
    KnowledgeProjectionWorker,
)


class _Gateway(IKnowledgeGateway):
    def __init__(self) -> None:
        self.upsert_documents = AsyncMock()
        self.delete_documents = AsyncMock()
        self.search = AsyncMock()

    @property
    def provider_name(self) -> str:
        return "test"

    def configuration_fingerprint(self) -> str:
        return "f" * 64

    async def check_readiness(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def search(self, query: KnowledgeSearchQuery) -> KnowledgeSearchResult:
        _ = query
        return KnowledgeSearchResult()


def _projection(**changes) -> KnowledgeIndexProjectionDE:
    values = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "knowledge_pack_id": uuid.uuid4(),
        "knowledge_pack_version_id": uuid.uuid4(),
        "provider": "test",
        "target_fingerprint": "f" * 64,
        "content_checksum": "c" * 64,
        "projection_schema_version": 1,
        "operation": "publish",
        "status": "processing",
        "document_count": 1,
        "attempt_count": 1,
        "max_attempts": 3,
        "requested_by_user_id": uuid.uuid4(),
        "requested_at": datetime.now(timezone.utc),
        "row_version": 2,
    }
    values.update(changes)
    return KnowledgeIndexProjectionDE(**values)


def _document(projection: KnowledgeIndexProjectionDE) -> KnowledgeIndexDocument:
    return KnowledgeIndexDocument(
        document_id=str(uuid.uuid4()),
        tenant_id=projection.tenant_id,
        knowledge_pack_id=projection.knowledge_pack_id,
        knowledge_pack_version_id=projection.knowledge_pack_version_id,
        knowledge_entry_id=uuid.uuid4(),
        knowledge_entry_revision_id=uuid.uuid4(),
        knowledge_scope_id=uuid.uuid4(),
        entry_key="key",
        title="Title",
        content="Approved body",
        content_checksum="d" * 64,
        projection_schema_version=1,
        channel="web",
    )


class TestKnowledgePackStagedActions(unittest.IsolatedAsyncioTestCase):
    """Covers gateway-enabled publish, rollback, archive, and reindex action paths."""

    def _service(self) -> KnowledgePackVersionService:
        return KnowledgePackVersionService(
            table="knowledge_pack_knowledge_pack_version",
            rsg=Mock(),
        )

    async def test_publish_and_rollback_queue_without_relational_transition(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        gateway = _Gateway()
        queued = _projection(
            tenant_id=tenant_id,
            knowledge_pack_id=pack_id,
            knowledge_pack_version_id=version_id,
            status="queued",
        )
        for action, status, validation, operation in (
            ("action_publish", "approved", KnowledgePackPublishValidation, "publish"),
            (
                "action_rollback_version",
                "archived",
                KnowledgePackRollbackVersionValidation,
                "rollback",
            ),
        ):
            service = self._service()
            service._get_for_action = AsyncMock(  # pylint: disable=protected-access
                return_value=KnowledgePackVersionDE(
                    id=version_id,
                    tenant_id=tenant_id,
                    knowledge_pack_id=pack_id,
                    status=status,
                    row_version=1,
                )
            )
            service._validate_no_unreviewed_revisions = (
                AsyncMock()
            )  # pylint: disable=protected-access
            service._projection_service.gateway = Mock(
                return_value=gateway
            )  # pylint: disable=protected-access
            service._projection_service.queue_projection = AsyncMock(
                return_value=queued
            )  # pylint: disable=protected-access
            service.update = AsyncMock()
            result, response_status = await getattr(service, action)(
                tenant_id=tenant_id,
                entity_id=version_id,
                where={"tenant_id": tenant_id, "id": version_id},
                auth_user_id=actor_id,
                data=validation(row_version=1),
            )
            with self.subTest(action=action):
                self.assertEqual(response_status, 202)
                self.assertEqual(result["ProjectionId"], str(queued.id))
                projection_service = (
                    service._projection_service
                )  # pylint: disable=protected-access
                self.assertEqual(
                    projection_service.queue_projection.await_args.kwargs["operation"],
                    operation,
                )
                service.update.assert_not_awaited()

    async def test_archive_cancels_and_queues_cleanup(self) -> None:
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        for status in ("published", "archived"):
            service = self._service()
            service._get_for_action = AsyncMock(  # pylint: disable=protected-access
                return_value=KnowledgePackVersionDE(
                    id=version_id,
                    tenant_id=tenant_id,
                    knowledge_pack_id=pack_id,
                    status=status,
                    row_version=2,
                )
            )
            service._projection_service.gateway = Mock(
                return_value=_Gateway()
            )  # pylint: disable=protected-access
            service._cancel_pending_projections = (
                AsyncMock()
            )  # pylint: disable=protected-access
            service._projection_service.queue_projection = (
                AsyncMock(  # pylint: disable=protected-access
                    return_value=_projection(status="queued")
                )
            )
            service._update_version_with_row_version = (
                AsyncMock()
            )  # pylint: disable=protected-access
            service._transition_revisions = (
                AsyncMock()
            )  # pylint: disable=protected-access
            service._pack_service.get = AsyncMock(  # pylint: disable=protected-access
                return_value=KnowledgePackDE(current_version_id=version_id)
            )
            service._set_pack_current_version = (
                AsyncMock()
            )  # pylint: disable=protected-access
            service._record_approval = AsyncMock()  # pylint: disable=protected-access
            result = await service.action_archive(
                tenant_id=tenant_id,
                entity_id=version_id,
                where={"tenant_id": tenant_id, "id": version_id},
                auth_user_id=actor_id,
                data=KnowledgePackArchiveValidation(row_version=2),
            )
            with self.subTest(status=status):
                self.assertEqual(result, ("", 204))
                cancel_pending = (
                    service._cancel_pending_projections
                )  # pylint: disable=protected-access
                cancel_pending.assert_awaited_once()
                projection_service = (
                    service._projection_service
                )  # pylint: disable=protected-access
                self.assertEqual(
                    projection_service.queue_projection.await_args.kwargs["operation"],
                    "cleanup",
                )

    async def test_cancel_pending_projection_helper_and_error(self) -> None:
        service = self._service()
        tenant_id = uuid.uuid4()
        version_id = uuid.uuid4()
        service._projection_service.list = (
            AsyncMock(  # pylint: disable=protected-access
                return_value=[
                    KnowledgeIndexProjectionDE(id=None),
                    KnowledgeIndexProjectionDE(id=uuid.uuid4(), status="processing"),
                ]
            )
        )
        service._projection_service.update = (
            AsyncMock()
        )  # pylint: disable=protected-access
        cancel_pending = (
            service._cancel_pending_projections
        )  # pylint: disable=protected-access
        await cancel_pending(
            tenant_id=tenant_id,
            knowledge_pack_version_id=version_id,
        )
        projection_service = (
            service._projection_service
        )  # pylint: disable=protected-access
        projection_service.update.assert_awaited_once()
        changes = projection_service.update.await_args.kwargs["changes"]
        self.assertEqual(changes["status"], "cancelled")
        service._projection_service.list = (
            AsyncMock(  # pylint: disable=protected-access
                side_effect=SQLAlchemyError("db")
            )
        )
        with self.assertRaises(HTTPException) as ctx:
            await cancel_pending(
                tenant_id=tenant_id,
                knowledge_pack_version_id=version_id,
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_reindex_success_and_guards(self) -> None:
        tenant_id = uuid.uuid4()
        pack_id = uuid.uuid4()
        version_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        service = self._service()
        service._get_for_action = AsyncMock(  # pylint: disable=protected-access
            return_value=KnowledgePackVersionDE(
                knowledge_pack_id=pack_id,
                status="published",
                row_version=3,
            )
        )
        service._projection_service.gateway = Mock(
            return_value=_Gateway()
        )  # pylint: disable=protected-access
        service._projection_service.queue_projection = (
            AsyncMock(  # pylint: disable=protected-access
                return_value=_projection(status="queued")
            )
        )
        result, status = await service.action_reindex(
            tenant_id=tenant_id,
            entity_id=version_id,
            where={"id": version_id},
            auth_user_id=actor_id,
            data=KnowledgePackReindexValidation(row_version=3),
        )
        self.assertEqual(status, 202)
        self.assertEqual(result["Status"], "queued")

        for current, gateway, message in (
            (KnowledgePackVersionDE(status="approved"), _Gateway(), "Only published"),
            (KnowledgePackVersionDE(status="published"), _Gateway(), "KnowledgePackId"),
            (
                KnowledgePackVersionDE(status="published", knowledge_pack_id=pack_id),
                None,
                "not configured",
            ),
        ):
            service._get_for_action = AsyncMock(
                return_value=current
            )  # pylint: disable=protected-access
            service._projection_service.gateway = Mock(
                return_value=gateway
            )  # pylint: disable=protected-access
            with self.subTest(message=message), self.assertRaisesRegex(
                HTTPException, message
            ):
                await service.action_reindex(
                    tenant_id=tenant_id,
                    entity_id=version_id,
                    where={"id": version_id},
                    auth_user_id=actor_id,
                    data=KnowledgePackReindexValidation(row_version=3),
                )


class _FakeUow:
    def __init__(self, projection: KnowledgeIndexProjectionDE) -> None:
        self.projection = projection
        self.updates: list[tuple[str, dict, dict]] = []
        self.inserts: list[tuple[str, dict]] = []

    async def find(self, table, **kwargs):
        if table == "knowledge_pack_knowledge_index_projection":
            return [{"id": uuid.uuid4(), "is_current_ready": True}]
        if table == "knowledge_pack_knowledge_pack_version":
            return [{"id": uuid.uuid4(), "status": "published"}]
        if table == "knowledge_pack_knowledge_entry_revision":
            return [{"id": uuid.uuid4(), "status": "published"}]
        return []

    async def update_one(self, table, where, changes, **kwargs):
        _ = kwargs
        self.updates.append((table, dict(where), dict(changes)))
        if (
            table == "knowledge_pack_knowledge_index_projection"
            and where.get("id") == self.projection.id
        ):
            return {"id": self.projection.id}
        return {"id": where.get("id")}

    async def insert(self, table, record, **kwargs):
        _ = kwargs
        self.inserts.append((table, dict(record)))
        return dict(record)


class _FakeRsg:
    def __init__(self, uow: _FakeUow) -> None:
        self.uow = uow

    @asynccontextmanager
    async def unit_of_work(self):
        yield self.uow


class TestKnowledgeProjectionWorker(unittest.IsolatedAsyncioTestCase):
    """Covers leases, writes, verification, retries, and transactions."""

    def _worker(self, projection: KnowledgeIndexProjectionDE | None = None):
        selected = projection or _projection()
        uow = _FakeUow(selected)
        gateway = _Gateway()
        logger = Mock(info=Mock(), warning=Mock())
        worker = KnowledgeProjectionWorker(
            rsg=_FakeRsg(uow),  # type: ignore[arg-type]
            gateway=gateway,
            logging_gateway=logger,
            lease_seconds=10,
            poll_seconds=0.05,
            worker_id="worker-1",
        )
        return worker, gateway, logger, uow

    async def test_recover_claim_retry_limit_and_conflict(self) -> None:
        worker, _, logger, _ = self._worker()
        expired = _projection(
            status="processing",
            lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        worker._projection_service.list = AsyncMock(
            return_value=[expired]
        )  # pylint: disable=protected-access
        worker._projection_service.update = AsyncMock(
            return_value=expired
        )  # pylint: disable=protected-access
        self.assertEqual(
            await worker._recover_expired_leases(),
            1,  # pylint: disable=protected-access
        )
        logger.warning.assert_called()

        no_id = _projection(id=None, status="processing")
        not_recovered = _projection(status="processing")
        recovered = _projection(status="processing")
        worker._projection_service.list = AsyncMock(  # pylint: disable=protected-access
            return_value=[no_id, not_recovered, recovered]
        )
        worker._projection_service.update = AsyncMock(
            side_effect=[None, recovered]
        )  # pylint: disable=protected-access
        self.assertEqual(
            await worker._recover_expired_leases(),  # pylint: disable=protected-access
            1,
        )
        worker._projection_service.list = AsyncMock(return_value=[no_id])
        self.assertEqual(
            await worker._recover_expired_leases(),  # pylint: disable=protected-access
            0,
        )

        no_id = _projection(id=None, status="queued")
        exhausted = _projection(status="queued", attempt_count=3, max_attempts=3)
        conflicted = _projection(status="queued")
        not_claimed = _projection(status="queued")
        claimed = _projection(status="queued")
        worker._recover_expired_leases = AsyncMock(
            return_value=0
        )  # pylint: disable=protected-access
        worker._projection_service.list = AsyncMock(  # pylint: disable=protected-access
            return_value=[no_id, exhausted, conflicted, not_claimed, claimed]
        )

        async def update(*, where, changes):
            if where.get("id") == conflicted.id:
                raise RowVersionConflict("p")
            if where.get("id") == not_claimed.id:
                return None
            if where.get("id") == claimed.id:
                return KnowledgeIndexProjectionDE(**{**claimed.__dict__, **changes})
            return exhausted

        worker._projection_service.update = AsyncMock(
            side_effect=update
        )  # pylint: disable=protected-access
        result = await worker._claim_next()  # pylint: disable=protected-access
        self.assertEqual(result.id, claimed.id)
        self.assertEqual(result.status, "processing")

        worker._projection_service.list = AsyncMock(return_value=[not_claimed])
        worker._projection_service.update = AsyncMock(return_value=None)
        self.assertIsNone(
            await worker._claim_next()
        )  # pylint: disable=protected-access

    async def test_process_upsert_verify_cleanup_and_failure_boundaries(self) -> None:
        projection = _projection()
        worker, gateway, _, _ = self._worker(projection)
        document = _document(projection)
        projection.content_checksum = "checksum"
        worker._document_builder.build = AsyncMock(  # pylint: disable=protected-access
            return_value=([document], "checksum")
        )
        gateway.upsert_documents.return_value = KnowledgeGatewayWriteResult(
            "test", 1, 1
        )
        gateway.search.return_value = KnowledgeSearchResult(
            items=[
                KnowledgeSearchHit(
                    tenant_id=document.tenant_id,
                    knowledge_pack_id=document.knowledge_pack_id,
                    knowledge_pack_version_id=document.knowledge_pack_version_id,
                    knowledge_entry_id=document.knowledge_entry_id,
                    knowledge_entry_revision_id=document.knowledge_entry_revision_id,
                    knowledge_scope_id=document.knowledge_scope_id,
                    entry_key=document.entry_key,
                )
            ]
        )
        worker._lease_is_active = AsyncMock(
            return_value=True
        )  # pylint: disable=protected-access
        worker._finalize_ready = AsyncMock()  # pylint: disable=protected-access
        await worker._process(projection)  # pylint: disable=protected-access
        gateway.upsert_documents.assert_awaited_once_with([document])
        gateway.search.assert_awaited_once()
        finalize_ready = worker._finalize_ready  # pylint: disable=protected-access
        finalize_ready.assert_awaited_once_with(projection, document_count=1)

        cleanup = _projection(operation="cleanup")
        worker._finalize_cleanup = AsyncMock()  # pylint: disable=protected-access
        await worker._process(cleanup)  # pylint: disable=protected-access
        gateway.delete_documents.assert_awaited()
        worker._finalize_cleanup.assert_awaited_once_with(
            cleanup
        )  # pylint: disable=protected-access

        worker._lease_is_active = AsyncMock(
            return_value=False
        )  # pylint: disable=protected-access
        await worker._process(projection)  # pylint: disable=protected-access
        self.assertGreaterEqual(gateway.delete_documents.await_count, 2)

        worker._document_builder.build = AsyncMock(
            return_value=([], "changed")
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "content changed"):
            await worker._process(projection)  # pylint: disable=protected-access

    async def test_target_identity_verification_and_acknowledgement_guards(
        self,
    ) -> None:
        projection = _projection(provider="other")
        worker, gateway, _, _ = self._worker(projection)
        with self.assertRaisesRegex(RuntimeError, "provider changed"):
            worker._validate_target(projection)  # pylint: disable=protected-access
        projection.provider = "test"
        projection.target_fingerprint = "x" * 64
        with self.assertRaisesRegex(RuntimeError, "target changed"):
            worker._validate_target(projection)  # pylint: disable=protected-access
        projection.target_fingerprint = "f" * 64
        projection.id = None
        with self.assertRaisesRegex(RuntimeError, "identity is incomplete"):
            await worker._process(projection)  # pylint: disable=protected-access

        projection = _projection(content_checksum="ok")
        document = _document(projection)
        worker._document_builder.build = AsyncMock(
            return_value=([document], "ok")
        )  # pylint: disable=protected-access
        gateway.upsert_documents.return_value = KnowledgeGatewayWriteResult(
            "test", 0, 0, False
        )
        with self.assertRaisesRegex(RuntimeError, "acknowledge"):
            await worker._process(projection)  # pylint: disable=protected-access

        gateway.upsert_documents.return_value = KnowledgeGatewayWriteResult(
            "test", 1, 1
        )
        gateway.search.return_value = KnowledgeSearchResult(items=[])
        worker._lease_is_active = AsyncMock(
            return_value=True
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "verification"):
            await worker._process(projection)  # pylint: disable=protected-access

    async def test_finalize_publish_reindex_cleanup_and_failure(self) -> None:
        projection = _projection(operation="publish")
        worker, _, logger, uow = self._worker(projection)
        await worker._finalize_ready(
            projection, document_count=2
        )  # pylint: disable=protected-access
        self.assertTrue(
            any(
                table == "knowledge_pack_knowledge_pack"
                and changes["current_version_id"]
                == projection.knowledge_pack_version_id
                for table, _, changes in uow.updates
            )
        )
        self.assertEqual(uow.inserts[0][1]["action"], "publish")
        logger.info.assert_called()

        rollback = _projection(operation="rollback")
        worker, _, _, uow = self._worker(rollback)
        await worker._finalize_ready(
            rollback, document_count=1
        )  # pylint: disable=protected-access
        self.assertEqual(uow.inserts[0][1]["action"], "rollback_version")

        reindex = _projection(operation="reindex")
        worker, _, _, uow = self._worker(reindex)
        await worker._finalize_ready(
            reindex, document_count=1
        )  # pylint: disable=protected-access
        self.assertEqual(uow.inserts, [])

        cleanup = _projection(operation="cleanup")
        worker, _, _, uow = self._worker(cleanup)
        await worker._finalize_cleanup(cleanup)  # pylint: disable=protected-access
        self.assertTrue(
            any(
                changes.get("is_current_ready") is False
                for _, _, changes in uow.updates
            )
        )

        worker._projection_service.update = (
            AsyncMock()
        )  # pylint: disable=protected-access
        await worker._record_failure(
            _projection(attempt_count=1), RuntimeError()
        )  # pylint: disable=protected-access
        self.assertEqual(
            worker._projection_service.update.await_args.kwargs["changes"][
                "status"
            ],  # pylint: disable=protected-access
            "queued",
        )
        await worker._record_failure(
            _projection(attempt_count=3), RuntimeError()
        )  # pylint: disable=protected-access
        self.assertEqual(
            worker._projection_service.update.await_args.kwargs["changes"][
                "status"
            ],  # pylint: disable=protected-access
            "failed",
        )

    async def test_worker_lease_current_row_and_finalize_loss_paths(self) -> None:
        projection = _projection()
        worker, _, _, uow = self._worker(projection)
        worker._projection_service.get = AsyncMock(  # pylint: disable=protected-access
            side_effect=[projection, None]
        )
        self.assertTrue(
            await worker._lease_is_active(
                projection
            )  # pylint: disable=protected-access
        )
        self.assertFalse(
            await worker._lease_is_active(
                projection
            )  # pylint: disable=protected-access
        )

        uow.find = AsyncMock(
            return_value=[{"id": projection.id, "is_current_ready": True}]
        )
        uow.update_one = AsyncMock(return_value={"id": projection.id})
        await worker._unset_current_ready(
            uow, projection
        )  # pylint: disable=protected-access
        uow.update_one.assert_not_awaited()

        worker, _, _, uow = self._worker(projection)
        original_find = uow.find

        async def find_current_version(table, **kwargs):
            if table == "knowledge_pack_knowledge_pack_version":
                return [{"id": projection.knowledge_pack_version_id}]
            return await original_find(table, **kwargs)

        uow.find = find_current_version
        await worker._publish_relational(  # pylint: disable=protected-access
            uow, projection, datetime.now(timezone.utc)
        )

        worker, _, _, uow = self._worker(projection)

        async def lose_ready_lease(table, where, changes, **kwargs):
            _ = changes, kwargs
            if (
                table == "knowledge_pack_knowledge_index_projection"
                and where.get("id") == projection.id
            ):
                return None
            return {"id": where.get("id")}

        uow.update_one = lose_ready_lease
        with self.assertRaisesRegex(RuntimeError, "lost before finalization"):
            await worker._finalize_ready(  # pylint: disable=protected-access
                projection, document_count=1
            )

        cleanup = _projection(operation="cleanup")
        worker, _, _, uow = self._worker(cleanup)

        async def lose_cleanup_lease(table, where, changes, **kwargs):
            _ = changes, kwargs
            if (
                table == "knowledge_pack_knowledge_index_projection"
                and where.get("id") == cleanup.id
            ):
                return None
            return {"id": where.get("id")}

        uow.update_one = lose_cleanup_lease
        with self.assertRaisesRegex(RuntimeError, "cleanup lease was lost"):
            await worker._finalize_cleanup(cleanup)  # pylint: disable=protected-access

    async def test_run_once_heartbeat_stop_and_loop_error(self) -> None:
        projection = _projection()
        worker, _, logger, _ = self._worker(projection)
        worker._claim_next = AsyncMock(
            return_value=None
        )  # pylint: disable=protected-access
        self.assertFalse(await worker.run_once())

        worker._claim_next = AsyncMock(
            return_value=projection
        )  # pylint: disable=protected-access
        worker._process = AsyncMock(
            side_effect=RuntimeError("fail")
        )  # pylint: disable=protected-access
        worker._record_failure = AsyncMock()  # pylint: disable=protected-access
        await worker.run_once()
        worker._record_failure.assert_awaited_once()  # pylint: disable=protected-access

        worker._projection_service.update = AsyncMock(
            return_value=None
        )  # pylint: disable=protected-access
        with patch("asyncio.sleep", new=AsyncMock()):
            await worker._heartbeat(projection)  # pylint: disable=protected-access

        worker._projection_service.update = (
            AsyncMock(  # pylint: disable=protected-access
                side_effect=[projection, None]
            )
        )
        with patch("asyncio.sleep", new=AsyncMock()):
            await worker._heartbeat(projection)  # pylint: disable=protected-access

        worker._claim_next = AsyncMock(
            return_value=projection
        )  # pylint: disable=protected-access

        async def failed_heartbeat(_projection_row):
            raise RuntimeError("heartbeat")

        async def yielding_process(_projection_row):
            await asyncio.sleep(0)

        setattr(worker, "_heartbeat", failed_heartbeat)
        setattr(worker, "_process", yielding_process)
        logger.warning.reset_mock()
        await worker.run_once()
        logger.warning.assert_called()

        await worker.stop()
        await worker.aclose()
        await worker.run()
        self.assertTrue(worker._stop.is_set())  # pylint: disable=protected-access

    async def test_worker_loop_processed_idle_timeout_and_poll_error(self) -> None:
        worker, _, logger, _ = self._worker()
        calls = 0

        async def processed_then_stop():
            nonlocal calls
            calls += 1
            if calls == 1:
                return True
            worker._stop.set()  # pylint: disable=protected-access
            return False

        worker.run_once = processed_then_stop  # type: ignore[method-assign]
        await worker.run()
        self.assertEqual(calls, 2)

        worker, _, _, _ = self._worker()
        worker.run_once = AsyncMock(return_value=False)  # type: ignore[method-assign]

        async def timeout_and_stop(awaitable, *, timeout):
            _ = timeout
            awaitable.close()
            worker._stop.set()  # pylint: disable=protected-access
            raise asyncio.TimeoutError

        with patch("asyncio.wait_for", new=timeout_and_stop):
            await worker.run()

        worker, _, logger, _ = self._worker()

        async def fail_poll():
            worker._stop.set()  # pylint: disable=protected-access
            raise RuntimeError("poll")

        worker.run_once = fail_poll  # type: ignore[method-assign]
        await worker.run()
        logger.warning.assert_called()


class TestKnowledgePackRuntimeWiring(unittest.IsolatedAsyncioTestCase):
    """Covers conditional worker and retrieval registration in the FW extension."""

    async def test_setup_with_and_without_gateway(self) -> None:
        app = Mock(add_background_task=Mock())
        logger = Mock()
        register = Mock()
        with patch(
            "mugen.core.plugin.knowledge_pack.fw_ext.di.container",
            SimpleNamespace(register_ext_services=register),
        ):
            extension = KnowledgePackFWExtension(
                rsg_provider=lambda: Mock(),
                gateway_provider=lambda: None,
                logging_provider=lambda: logger,
            )
            await extension.setup(app)
            register.assert_not_called()
            app.add_background_task.assert_not_called()

            gateway = _Gateway()
            extension = KnowledgePackFWExtension(
                rsg_provider=lambda: Mock(),
                gateway_provider=lambda: gateway,
                logging_provider=lambda: logger,
            )
            await extension.setup(app)
            register.assert_called_once()
            app.add_background_task.assert_called_once()

        gateway = _Gateway()
        container = SimpleNamespace(
            relational_storage_gateway=Mock(),
            knowledge_gateway=gateway,
            logging_gateway=logger,
            register_ext_services=Mock(),
        )
        with patch(
            "mugen.core.plugin.knowledge_pack.fw_ext.di.container",
            container,
        ):
            extension = KnowledgePackFWExtension()
            self.assertEqual(extension.platforms, [])
        configure_knowledge_gateway(None)
