"""Tests for DedupRecordService behavior."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
from datetime import datetime, timedelta, timezone
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import IntegrityError, SQLAlchemyError


def _bootstrap_namespace_packages() -> None:
    root = Path(__file__).resolve().parents[1] / "mugen"

    if "mugen" not in sys.modules:
        mugen_pkg = ModuleType("mugen")
        mugen_pkg.__path__ = [str(root)]
        sys.modules["mugen"] = mugen_pkg

    if "mugen.core" not in sys.modules:
        core_pkg = ModuleType("mugen.core")
        core_pkg.__path__ = [str(root / "core")]
        sys.modules["mugen.core"] = core_pkg
        setattr(sys.modules["mugen"], "core", core_pkg)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.service import dedup_record as dedup_mod
from mugen.core.plugin.acp.service.dedup_record import DedupRecordService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _build_service(*, strict_request_hash: bool = False) -> DedupRecordService:
    service = DedupRecordService.__new__(DedupRecordService)
    service._config_provider = lambda: SimpleNamespace(
        acp=SimpleNamespace(
            idempotency=SimpleNamespace(
                default_ttl_seconds=3600,
                default_lease_seconds=30,
                strict_request_hash=strict_request_hash,
            )
        )
    )
    service.get = AsyncMock()
    service.create = AsyncMock()
    service.update_with_row_version = AsyncMock()
    service.list = AsyncMock()
    service.delete = AsyncMock()
    return service


class TestMugenAcpServiceDedupRecord(unittest.IsolatedAsyncioTestCase):
    """Covers acquire/commit/sweep decision branches."""

    async def test_acquire_new_record_returns_acquired(self) -> None:
        service = _build_service()
        record = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=1,
            status="in_progress",
            lease_expires_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        service.get.return_value = None
        service.create.return_value = record

        result = await service.acquire(
            tenant_id=uuid.uuid4(),
            scope="acp:create:Users",
            idempotency_key="key-1",
            request_hash="h1",
            owner_instance="owner-1",
        )

        self.assertEqual(result["decision"], "acquired")
        self.assertEqual(result["record"].id, record.id)
        service.create.assert_awaited_once()

    async def test_acquire_strict_hash_mismatch_returns_conflict(self) -> None:
        service = _build_service(strict_request_hash=True)
        record = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=1,
            request_hash="existing-hash",
            status="in_progress",
            owner_instance="owner-1",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        service.get.return_value = record

        result = await service.acquire(
            tenant_id=uuid.uuid4(),
            scope="acp:create:Users",
            idempotency_key="key-1",
            request_hash="different-hash",
            owner_instance="owner-1",
        )

        self.assertEqual(result["decision"], "conflict")

    async def test_acquire_replay_and_in_progress_decisions(self) -> None:
        service = _build_service()
        replay_record = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=1,
            request_hash="hash",
            status="succeeded",
            response_code=200,
            response_payload={"ok": True},
            owner_instance=None,
            lease_expires_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        service.get.return_value = replay_record

        replay_result = await service.acquire(
            tenant_id=uuid.uuid4(),
            scope="acp:create:Users",
            idempotency_key="key-1",
            request_hash="hash",
            owner_instance="owner-1",
        )
        self.assertEqual(replay_result["decision"], "replay")

        in_progress_record = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=1,
            request_hash="hash",
            status="in_progress",
            owner_instance="owner-2",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        service.get.return_value = in_progress_record

        in_progress_result = await service.acquire(
            tenant_id=uuid.uuid4(),
            scope="acp:create:Users",
            idempotency_key="key-1",
            request_hash="hash",
            owner_instance="owner-1",
        )
        self.assertEqual(in_progress_result["decision"], "in_progress")

    async def test_acquire_takes_over_expired_lease(self) -> None:
        service = _build_service()
        stale_record = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=2,
            request_hash="hash",
            status="in_progress",
            owner_instance="owner-2",
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        updated_record = SimpleNamespace(
            **{
                **stale_record.__dict__,
                "owner_instance": "owner-1",
            }
        )
        service.get.return_value = stale_record
        service.update_with_row_version.return_value = updated_record

        result = await service.acquire(
            tenant_id=uuid.uuid4(),
            scope="acp:create:Users",
            idempotency_key="key-1",
            request_hash="hash",
            owner_instance="owner-1",
        )

        self.assertEqual(result["decision"], "acquired")
        self.assertEqual(result["record"].owner_instance, "owner-1")

    async def test_commit_success_and_failure_update_rows(self) -> None:
        service = _build_service()
        row = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=3,
            status="in_progress",
        )
        service.get.return_value = row
        service.update_with_row_version.return_value = row

        await service.commit_success(
            entity_id=row.id,
            response_code=201,
            response_payload={"ok": True},
            result_ref="users/1",
        )
        await service.commit_failure(
            entity_id=row.id,
            response_code=500,
            response_payload={"Error": "boom"},
            error_code="error",
            error_message="boom",
        )

        self.assertEqual(service.update_with_row_version.await_count, 2)

    async def test_sweep_expired_deletes_bounded_batch(self) -> None:
        service = _build_service()
        rows = [SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4())]
        service.list.return_value = rows
        service.delete.side_effect = [rows[0], None]

        deleted = await service.sweep_expired(
            tenant_id=uuid.uuid4(),
            batch_size=100,
        )

        self.assertEqual(deleted, 1)
        self.assertEqual(service.delete.await_count, 2)

    def test_constructor_and_helper_paths(self) -> None:
        sentinel_config = SimpleNamespace(sample=True)
        with patch.object(
            dedup_mod.di, "container", new=SimpleNamespace(config=sentinel_config)
        ):
            self.assertIs(dedup_mod._config_provider(), sentinel_config)

        svc = DedupRecordService(table="admin_dedup_record", rsg=SimpleNamespace())
        now = datetime.now(timezone.utc)
        self.assertFalse(svc._is_expired(None, now))
        self.assertFalse(svc._lease_active(None, now))
        self.assertIsNone(svc._serialize_datetime(None))
        self.assertIsNotNone(svc._serialize_datetime(datetime(2026, 1, 1)))
        self.assertIsNone(svc._parse_positive_int("bad"))
        self.assertIsNone(svc._parse_positive_int(0))
        self.assertEqual(svc._parse_positive_int("5"), 5)

        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                svc._normalize_text("   ", field="Scope")
            self.assertEqual(ex.exception.code, 400)

    async def test_acquire_create_error_paths(self) -> None:
        service = _build_service()
        service.get.side_effect = [None, None]
        service.create.side_effect = IntegrityError(
            "insert", {}, Exception("dup"), None
        )

        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.acquire(
                    tenant_id=uuid.uuid4(),
                    scope="acp:create:Users",
                    idempotency_key="key-1",
                    request_hash="h1",
                    owner_instance="owner-1",
                )
            self.assertEqual(ex.exception.code, 500)

        service = _build_service()
        service.get.return_value = None
        service.create.side_effect = SQLAlchemyError("db")
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.acquire(
                    tenant_id=uuid.uuid4(),
                    scope="acp:create:Users",
                    idempotency_key="key-1",
                    request_hash="h1",
                    owner_instance="owner-1",
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_acquire_create_integrity_then_existing_record_path(self) -> None:
        service = _build_service()
        existing = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=1,
            request_hash="h1",
            status="succeeded",
            response_code=200,
            response_payload={"Replay": True},
            owner_instance=None,
            lease_expires_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        service.get.side_effect = [None, existing]
        service.create.side_effect = IntegrityError(
            "insert", {}, Exception("dup"), None
        )

        result = await service.acquire(
            tenant_id=uuid.uuid4(),
            scope="acp:create:Users",
            idempotency_key="key-1",
            request_hash="h1",
            owner_instance="owner-1",
        )
        self.assertEqual(result["decision"], "replay")

    async def test_acquire_expired_row_paths(self) -> None:
        service = _build_service()
        expired = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=3,
            status="in_progress",
            request_hash="hash",
            owner_instance="o1",
            lease_expires_at=None,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        reacquired = SimpleNamespace(**{**expired.__dict__, "row_version": 4})
        service.get.side_effect = [expired, reacquired]
        service.update_with_row_version.side_effect = RowVersionConflict("rv")

        result = await service.acquire(
            tenant_id=uuid.uuid4(),
            scope="acp:create:Users",
            idempotency_key="key-1",
            request_hash="hash",
            owner_instance="owner-1",
        )
        self.assertEqual(result["decision"], "acquired")

        service = _build_service()
        service.get.return_value = expired
        service.update_with_row_version.side_effect = SQLAlchemyError("db")
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.acquire(
                    tenant_id=uuid.uuid4(),
                    scope="acp:create:Users",
                    idempotency_key="key-1",
                    request_hash="hash",
                    owner_instance="owner-1",
                )
            self.assertEqual(ex.exception.code, 500)

        service = _build_service()
        service.get.return_value = expired
        service.update_with_row_version.return_value = None
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.acquire(
                    tenant_id=uuid.uuid4(),
                    scope="acp:create:Users",
                    idempotency_key="key-1",
                    request_hash="hash",
                    owner_instance="owner-1",
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_acquire_update_conflict_and_db_error_paths(self) -> None:
        service = _build_service(strict_request_hash=True)
        row = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=2,
            status="in_progress",
            request_hash="same-hash",
            owner_instance="owner-1",
            lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        updated = SimpleNamespace(**{**row.__dict__, "row_version": 3})
        service.get.side_effect = [row, updated]
        service.update_with_row_version.side_effect = RowVersionConflict("rv")
        result = await service.acquire(
            tenant_id=uuid.uuid4(),
            scope="acp:create:Users",
            idempotency_key="key-1",
            request_hash="same-hash",
            owner_instance="owner-1",
        )
        self.assertEqual(result["decision"], "acquired")

        service = _build_service()
        service.get.return_value = row
        service.update_with_row_version.side_effect = SQLAlchemyError("db")
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.acquire(
                    tenant_id=uuid.uuid4(),
                    scope="acp:create:Users",
                    idempotency_key="key-1",
                    request_hash="hash",
                    owner_instance="owner-1",
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_commit_error_paths(self) -> None:
        record_id = uuid.uuid4()
        service = _build_service()
        service.get.return_value = None
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.commit_success(
                    entity_id=record_id,
                    response_code=200,
                    response_payload={},
                    result_ref=None,
                )
            self.assertEqual(ex.exception.code, 404)

        service = _build_service()
        service.get.return_value = SimpleNamespace(
            id=record_id, row_version=1, status="failed"
        )
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.commit_success(
                    entity_id=record_id,
                    response_code=200,
                    response_payload={},
                    result_ref=None,
                )
            self.assertEqual(ex.exception.code, 409)

        in_progress = SimpleNamespace(id=record_id, row_version=1, status="in_progress")
        service = _build_service()
        service.get.return_value = in_progress
        service.update_with_row_version.side_effect = RowVersionConflict("rv")
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.commit_success(
                    entity_id=record_id,
                    response_code=200,
                    response_payload={},
                    result_ref=None,
                )
            self.assertEqual(ex.exception.code, 409)

        service = _build_service()
        service.get.return_value = in_progress
        service.update_with_row_version.side_effect = SQLAlchemyError("db")
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.commit_success(
                    entity_id=record_id,
                    response_code=200,
                    response_payload={},
                    result_ref=None,
                )
            self.assertEqual(ex.exception.code, 500)

        service = _build_service()
        service.get.return_value = in_progress
        service.update_with_row_version.return_value = None
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.commit_success(
                    entity_id=record_id,
                    response_code=200,
                    response_payload={},
                    result_ref=None,
                )
            self.assertEqual(ex.exception.code, 404)

        service = _build_service()
        service.get.return_value = None
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.commit_failure(
                    entity_id=record_id,
                    response_code=500,
                    response_payload={},
                    error_code=None,
                    error_message=None,
                )
            self.assertEqual(ex.exception.code, 404)

        service = _build_service()
        service.get.return_value = SimpleNamespace(
            id=record_id, row_version=1, status="succeeded"
        )
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.commit_failure(
                    entity_id=record_id,
                    response_code=500,
                    response_payload={},
                    error_code=None,
                    error_message=None,
                )
            self.assertEqual(ex.exception.code, 409)

        service = _build_service()
        service.get.return_value = in_progress
        service.update_with_row_version.side_effect = RowVersionConflict("rv")
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.commit_failure(
                    entity_id=record_id,
                    response_code=500,
                    response_payload={},
                    error_code=None,
                    error_message=None,
                )
            self.assertEqual(ex.exception.code, 409)

        service = _build_service()
        service.get.return_value = in_progress
        service.update_with_row_version.side_effect = SQLAlchemyError("db")
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.commit_failure(
                    entity_id=record_id,
                    response_code=500,
                    response_payload={},
                    error_code=None,
                    error_message=None,
                )
            self.assertEqual(ex.exception.code, 500)

        service = _build_service()
        service.get.return_value = in_progress
        service.update_with_row_version.return_value = None
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.commit_failure(
                    entity_id=record_id,
                    response_code=500,
                    response_payload={},
                    error_code=None,
                    error_message=None,
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_sweep_expired_no_tenant_and_delete_error(self) -> None:
        service = _build_service()
        service.list.return_value = [SimpleNamespace(id=uuid.uuid4())]
        service.delete.side_effect = SQLAlchemyError("db")

        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.sweep_expired(tenant_id=None, batch_size=None)
            self.assertEqual(ex.exception.code, 500)

    async def test_action_wrappers_and_format_result_paths(self) -> None:
        service = _build_service()
        record = SimpleNamespace(
            id=uuid.uuid4(),
            status="succeeded",
            lease_expires_at=datetime.now(timezone.utc),
            result_ref="users/1",
            error_code=None,
            error_message=None,
        )
        service.acquire = AsyncMock(
            return_value={
                "decision": "replay",
                "record": record,
                "response_code": 202,
                "response_payload": {"Replay": True},
            }
        )
        service.commit_success = AsyncMock()
        service.commit_failure = AsyncMock()
        service.sweep_expired = AsyncMock(return_value=2)
        auth_user = uuid.uuid4()
        tenant_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        payload, status = await service.entity_set_action_acquire(
            auth_user_id=auth_user,
            data=SimpleNamespace(
                tenant_id=None,
                scope="acp:create:Users",
                idempotency_key="k1",
                request_hash="h1",
                owner_instance="o1",
                ttl_seconds=10,
                lease_seconds=5,
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["Decision"], "replay")
        self.assertEqual(payload["ResponseCode"], 202)

        payload, status = await service.action_acquire(
            tenant_id=tenant_id,
            where={},
            auth_user_id=auth_user,
            data=SimpleNamespace(
                scope="acp:create:Users",
                idempotency_key="k1",
                request_hash="h1",
                owner_instance="o1",
                ttl_seconds=10,
                lease_seconds=5,
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["Id"], str(record.id))

        _, status = await service.entity_action_commit_success(
            entity_id=entity_id,
            auth_user_id=auth_user,
            data=SimpleNamespace(
                response_code=201,
                response_payload={"ok": True},
                result_ref="users/1",
                ttl_seconds=10,
            ),
        )
        self.assertEqual(status, 204)

        _, status = await service.action_commit_success(
            tenant_id=tenant_id,
            entity_id=entity_id,
            where={},
            auth_user_id=auth_user,
            data=SimpleNamespace(
                response_code=201,
                response_payload={"ok": True},
                result_ref="users/1",
                ttl_seconds=10,
            ),
        )
        self.assertEqual(status, 204)

        _, status = await service.entity_action_commit_failure(
            entity_id=entity_id,
            auth_user_id=auth_user,
            data=SimpleNamespace(
                response_code=500,
                response_payload={"error": True},
                error_code="error",
                error_message="boom",
                ttl_seconds=10,
            ),
        )
        self.assertEqual(status, 204)

        _, status = await service.action_commit_failure(
            tenant_id=tenant_id,
            entity_id=entity_id,
            where={},
            auth_user_id=auth_user,
            data=SimpleNamespace(
                response_code=500,
                response_payload={"error": True},
                error_code="error",
                error_message="boom",
                ttl_seconds=10,
            ),
        )
        self.assertEqual(status, 204)

        sweep_payload, status = await service.entity_set_action_sweep_expired(
            auth_user_id=auth_user,
            data=SimpleNamespace(tenant_id=None, batch_size=100),
        )
        self.assertEqual(status, 200)
        self.assertEqual(sweep_payload["DeletedCount"], 2)

        sweep_payload, status = await service.action_sweep_expired(
            tenant_id=tenant_id,
            where={},
            auth_user_id=auth_user,
            data=SimpleNamespace(batch_size=100),
        )
        self.assertEqual(status, 200)
        self.assertEqual(sweep_payload["DeletedCount"], 2)

        non_replay_payload = (
            service._format_action_result(  # pylint: disable=protected-access
                {"decision": "acquired", "record": record}
            )
        )
        self.assertNotIn("ResponseCode", non_replay_payload)

    async def test_action_acquire_conflict_aborts(self) -> None:
        service = _build_service()
        service.acquire = AsyncMock(
            return_value={"decision": "conflict", "message": "hash mismatch"}
        )
        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.entity_set_action_acquire(
                    auth_user_id=uuid.uuid4(),
                    data=SimpleNamespace(
                        tenant_id=None,
                        scope="acp:create:Users",
                        idempotency_key="k1",
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

        with patch.object(dedup_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await service.action_acquire(
                    tenant_id=uuid.uuid4(),
                    where={},
                    auth_user_id=uuid.uuid4(),
                    data=SimpleNamespace(
                        scope="acp:create:Users",
                        idempotency_key="k1",
                    ),
                )
            self.assertEqual(ex.exception.code, 409)
