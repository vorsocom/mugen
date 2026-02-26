"""Unit tests for audit EvidenceBlob service lifecycle behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException


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

    if "mugen.core.di" not in sys.modules:
        di_mod = ModuleType("mugen.core.di")
        di_mod.container = SimpleNamespace(config=SimpleNamespace())
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RowVersionConflict,
    ScalarFilterOp,
)
from mugen.core.plugin.audit.service import evidence_blob as evidence_blob_mod
from mugen.core.plugin.audit.service.evidence_blob import EvidenceBlobService


class _FakeUow:
    def __init__(self, gateway: "_FakeRsg"):
        self._gateway = gateway

    async def get_one(self, table: str, where: dict, *, columns=None):  # noqa: ARG002
        return self._gateway._get_row(table, where)

    async def insert(self, table: str, record: dict, *, returning: bool = True):
        row = self._gateway._insert_row(table, record)
        if returning:
            return row
        return None

    async def update_one(
        self,
        table: str,
        where: dict,
        changes: dict,
        *,
        returning: bool = True,
    ):
        row = self._gateway._update_row(table, where, changes)
        if returning:
            return row
        return None


class _FakeRsg:
    def __init__(self):
        self.tables = {"audit_evidence_blob": []}

    @asynccontextmanager
    async def unit_of_work(self):
        yield _FakeUow(self)

    @staticmethod
    def _matches(row: dict, where: dict) -> bool:
        return all(row.get(key) == value for key, value in where.items())

    def _insert_row(self, table: str, record: dict) -> dict:
        now = datetime.now(timezone.utc)
        row = dict(record)
        row.setdefault("id", uuid.uuid4())
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        row.setdefault("row_version", 1)
        self.tables[table].append(row)
        return dict(row)

    def _get_row(self, table: str, where: dict) -> dict | None:
        for row in self.tables[table]:
            if self._matches(row, where):
                return dict(row)
        return None

    def _update_row(self, table: str, where: dict, changes: dict) -> dict | None:
        expected_version = where.get("row_version")
        for row in self.tables[table]:
            if expected_version is not None:
                identity_where = dict(where)
                identity_where.pop("row_version", None)
                if not self._matches(row, identity_where):
                    continue
                if row.get("row_version") != expected_version:
                    raise RowVersionConflict(table, where)
            if not self._matches(row, where):
                continue

            row.update(dict(changes))
            if "row_version" in row and "row_version" not in changes:
                row["row_version"] = int(row["row_version"]) + 1
            row["updated_at"] = datetime.now(timezone.utc)
            return dict(row)
        return None

    @staticmethod
    def _scalar_match(value, op: ScalarFilterOp, expected) -> bool:
        if op == ScalarFilterOp.EQ:
            return value == expected
        if op == ScalarFilterOp.NE:
            return value != expected
        if value is None or expected is None:
            return False
        if op == ScalarFilterOp.GT:
            return value > expected
        if op == ScalarFilterOp.GTE:
            return value >= expected
        if op == ScalarFilterOp.LT:
            return value < expected
        if op == ScalarFilterOp.LTE:
            return value <= expected
        return False

    @classmethod
    def _group_match(cls, row: dict, group: FilterGroup) -> bool:
        if not cls._matches(row, dict(group.where)):
            return False
        for scalar in group.scalar_filters:
            if not cls._scalar_match(row.get(scalar.field), scalar.op, scalar.value):
                return False
        return True

    async def get_one(self, table: str, where: dict, *, columns=None):  # noqa: ARG002
        return self._get_row(table, where)

    async def insert_one(self, table: str, record: dict):
        return self._insert_row(table, record)

    async def update_one(self, table: str, where: dict, changes: dict):
        return self._update_row(table, where, changes)

    async def delete_one(self, table: str, where: dict):
        expected_version = where.get("row_version")
        for idx, row in enumerate(self.tables[table]):
            if expected_version is not None:
                identity_where = dict(where)
                identity_where.pop("row_version", None)
                if not self._matches(row, identity_where):
                    continue
                if row.get("row_version") != expected_version:
                    raise RowVersionConflict(table, where)
            if not self._matches(row, where):
                continue
            deleted = self.tables[table].pop(idx)
            return dict(deleted)
        return None

    async def delete_many(self, table: str, where: dict):
        self.tables[table] = [
            row for row in self.tables[table] if not self._matches(row, where)
        ]

    async def find_many(
        self,
        table: str,
        *,
        columns=None,  # noqa: ARG002
        filter_groups=None,
        order_by=None,
        limit=None,
        offset=None,
    ):
        rows = [dict(row) for row in self.tables[table]]

        if filter_groups:
            rows = [
                row
                for row in rows
                if any(self._group_match(row, group) for group in filter_groups)
            ]

        for ordering in reversed(order_by or []):
            rows.sort(
                key=lambda row: (
                    row.get(ordering.field) is None,
                    row.get(ordering.field),
                ),
                reverse=bool(ordering.descending),
            )

        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows

    async def count_many(self, table: str, *, filter_groups=None):
        rows = await self.find_many(table, filter_groups=filter_groups)
        return len(rows)


class _Registry:
    def __init__(self, audit_svc):
        self._audit_svc = audit_svc

    def get_resource(self, _name: str):
        return SimpleNamespace(service_key="audit")

    def get_edm_service(self, _key: str):
        return self._audit_svc


class TestEvidenceBlobService(unittest.IsolatedAsyncioTestCase):
    """Covers register/verify/hold/redact/tombstone/purge and lifecycle runner."""

    async def asyncSetUp(self) -> None:
        self.tenant_id = uuid.uuid4()
        self.actor_id = uuid.uuid4()
        self.gateway = _FakeRsg()
        self.audit_svc = AsyncMock()
        self.service = EvidenceBlobService(
            table="audit_evidence_blob",
            rsg=self.gateway,
            config_provider=lambda: SimpleNamespace(
                audit=SimpleNamespace(lifecycle=SimpleNamespace(purge_grace_days=0))
            ),
            registry_provider=lambda: _Registry(self.audit_svc),
        )

    def _find_row(self, evidence_id: uuid.UUID) -> dict:
        for row in self.gateway.tables["audit_evidence_blob"]:
            if row["id"] == evidence_id:
                return row
        raise AssertionError("expected row not found")

    async def test_helpers_and_emit_error_paths(self) -> None:
        now = datetime(2026, 2, 25, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(self.service._to_aware_utc(now), now)
        naive = datetime(2026, 2, 25, 22, 0)
        self.assertEqual(self.service._to_aware_utc(naive).tzinfo, timezone.utc)
        self.assertIsNone(self.service._to_aware_utc(None))

        bad_cfg_service = EvidenceBlobService(
            table="audit_evidence_blob",
            rsg=self.gateway,
            config_provider=lambda: SimpleNamespace(
                audit=SimpleNamespace(lifecycle=SimpleNamespace(purge_grace_days="bad"))
            ),
            registry_provider=lambda: (_ for _ in ()).throw(RuntimeError("missing")),
        )
        self.assertEqual(bad_cfg_service._default_purge_grace_days(), 30)

        await bad_cfg_service._emit_lifecycle_event(
            tenant_id=self.tenant_id,
            actor_id=self.actor_id,
            entity_id=uuid.uuid4(),
            action_name="noop",
            outcome="success",
        )

        broken_audit = AsyncMock()
        broken_audit.create = AsyncMock(side_effect=RuntimeError("boom"))
        svc = EvidenceBlobService(
            table="audit_evidence_blob",
            rsg=self.gateway,
            config_provider=lambda: SimpleNamespace(
                audit=SimpleNamespace(lifecycle=SimpleNamespace())
            ),
            registry_provider=lambda: _Registry(broken_audit),
        )
        await svc._emit_lifecycle_event(
            tenant_id=self.tenant_id,
            actor_id=self.actor_id,
            entity_id=uuid.uuid4(),
            action_name="noop",
            outcome="success",
        )

    async def test_registry_provider_validation_and_lookup_errors(self) -> None:
        with patch.object(
            evidence_blob_mod.di,
            "container",
            new=SimpleNamespace(
                config=SimpleNamespace(),
                get_required_ext_service=lambda _key: "registry-service",
            ),
        ):
            self.assertEqual(evidence_blob_mod._registry_provider(), "registry-service")

        with self.assertRaises(HTTPException) as ctx:
            self.service._normalize_required_text("   ", field="StorageUri")
        self.assertEqual(ctx.exception.code, 400)

        self.service.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
        with self.assertRaises(HTTPException) as ctx:
            await self.service._get_for_action(
                where={"id": uuid.uuid4()},
                expected_row_version=1,
                not_found="missing",
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await self.service.entity_set_action_register(
                auth_user_id=self.actor_id,
                data=SimpleNamespace(
                    tenant_id=self.tenant_id,
                    storage_uri="s3://bucket/lookup-error",
                    content_hash="abc",
                    hash_alg="sha256",
                    immutability="immutable",
                ),
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_action_conflict_and_sql_error_paths(self) -> None:
        now = datetime(2026, 2, 25, 22, 0, tzinfo=timezone.utc)
        evidence_id = uuid.uuid4()

        verify_row = SimpleNamespace(
            id=evidence_id,
            tenant_id=self.tenant_id,
            content_hash="abc",
            hash_alg="sha256",
            verification_status="pending",
            verified_at=None,
        )
        self.service._get_for_action = AsyncMock(return_value=verify_row)
        self.service.update_with_row_version = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self.service._verify_hash(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(
                    row_version=1,
                    observed_hash="abc",
                    observed_hash_alg="sha256",
                ),
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await self.service._verify_hash(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(
                    row_version=1,
                    observed_hash="abc",
                    observed_hash_alg="sha256",
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

        inactive_hold_row = SimpleNamespace(
            id=evidence_id,
            tenant_id=self.tenant_id,
            legal_hold_at=None,
            legal_hold_released_at=None,
            legal_hold_until=None,
            legal_hold_reason=None,
            redacted_at=None,
            tombstoned_at=None,
            purged_at=None,
        )
        self.service._get_for_action = AsyncMock(return_value=inactive_hold_row)
        self.service.update_with_row_version = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self.service._place_legal_hold(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(
                    row_version=1,
                    reason="legal",
                    legal_hold_until=None,
                ),
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await self.service._place_legal_hold(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(
                    row_version=1,
                    reason="legal",
                    legal_hold_until=None,
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

        active_hold_row = SimpleNamespace(
            id=evidence_id,
            tenant_id=self.tenant_id,
            legal_hold_at=now,
            legal_hold_released_at=None,
            legal_hold_until=None,
            legal_hold_reason="hold",
            redacted_at=None,
            tombstoned_at=None,
            purged_at=None,
        )
        self.service._get_for_action = AsyncMock(return_value=active_hold_row)
        self.service.update_with_row_version = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self.service._release_legal_hold(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(row_version=1, reason="release"),
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await self.service._release_legal_hold(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(row_version=1, reason="release"),
            )
        self.assertEqual(ctx.exception.code, 409)

        self.service._get_for_action = AsyncMock(return_value=inactive_hold_row)
        self.service.update_with_row_version = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self.service._redact(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(row_version=1, reason="pii"),
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await self.service._redact(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(row_version=1, reason="pii"),
            )
        self.assertEqual(ctx.exception.code, 409)

        self.service._get_for_action = AsyncMock(return_value=active_hold_row)
        with self.assertRaises(HTTPException) as ctx:
            await self.service._tombstone(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(row_version=1, reason="retention"),
            )
        self.assertEqual(ctx.exception.code, 409)

        self.service._get_for_action = AsyncMock(return_value=inactive_hold_row)
        self.service.update_with_row_version = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self.service._tombstone(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(row_version=1, reason="retention"),
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await self.service._tombstone(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(row_version=1, reason="retention"),
            )
        self.assertEqual(ctx.exception.code, 409)

        self.service._get_for_action = AsyncMock(return_value=active_hold_row)
        with self.assertRaises(HTTPException) as ctx:
            await self.service._purge(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(row_version=1, reason="purge"),
            )
        self.assertEqual(ctx.exception.code, 409)

        self.service._get_for_action = AsyncMock(return_value=inactive_hold_row)
        self.service.update_with_row_version = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self.service._purge(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(row_version=1, reason="purge"),
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await self.service._purge(
                where={"id": evidence_id},
                auth_user_id=self.actor_id,
                data=SimpleNamespace(row_version=1, reason="purge"),
            )
        self.assertEqual(ctx.exception.code, 409)

    async def test_lifecycle_phase_edge_and_error_paths(self) -> None:
        now = datetime(2026, 2, 25, 22, 0, tzinfo=timezone.utc)
        row_id = uuid.uuid4()
        base_row = SimpleNamespace(
            id=row_id,
            row_version=1,
            legal_hold_at=None,
            legal_hold_released_at=None,
            legal_hold_until=None,
        )
        held_row = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=1,
            legal_hold_at=now,
            legal_hold_released_at=None,
            legal_hold_until=None,
        )

        redact_zero = await self.service._phase_redact_due(
            tenant_id=None,
            dry_run=False,
            batch_size=10,
            max_batches=0,
            now=now,
        )
        self.assertEqual(redact_zero["RowsProcessed"], 0)

        tombstone_zero = await self.service._phase_tombstone_expired(
            tenant_id=None,
            dry_run=False,
            batch_size=10,
            max_batches=0,
            now=now,
        )
        self.assertEqual(tombstone_zero["RowsProcessed"], 0)

        purge_zero = await self.service._phase_purge_due(
            tenant_id=None,
            dry_run=False,
            batch_size=10,
            max_batches=0,
            now=now,
        )
        self.assertEqual(purge_zero["RowsProcessed"], 0)

        self.service.count = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await self.service._phase_redact_due(
                tenant_id=self.tenant_id,
                dry_run=True,
                batch_size=10,
                max_batches=1,
                now=now,
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.count = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await self.service._phase_tombstone_expired(
                tenant_id=self.tenant_id,
                dry_run=True,
                batch_size=10,
                max_batches=1,
                now=now,
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.count = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await self.service._phase_purge_due(
                tenant_id=self.tenant_id,
                dry_run=True,
                batch_size=10,
                max_batches=1,
                now=now,
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.list = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await self.service._phase_redact_due(
                tenant_id=self.tenant_id,
                dry_run=False,
                batch_size=10,
                max_batches=1,
                now=now,
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.list = AsyncMock(side_effect=[[held_row], []])
        self.service.update_with_row_version = AsyncMock()
        redact_summary = await self.service._phase_redact_due(
            tenant_id=self.tenant_id,
            dry_run=False,
            batch_size=10,
            max_batches=2,
            now=now,
        )
        self.assertEqual(redact_summary["RowsProcessed"], 0)
        self.assertEqual(redact_summary["Batches"], 1)

        self.service.list = AsyncMock(side_effect=[[base_row], []])
        self.service.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict(
                "audit_evidence_blob",
                {"id": base_row.id},
            )
        )
        redact_summary = await self.service._phase_redact_due(
            tenant_id=self.tenant_id,
            dry_run=False,
            batch_size=10,
            max_batches=2,
            now=now,
        )
        self.assertEqual(redact_summary["RowsProcessed"], 0)

        self.service.list = AsyncMock(return_value=[base_row])
        self.service.update_with_row_version = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self.service._phase_redact_due(
                tenant_id=self.tenant_id,
                dry_run=False,
                batch_size=10,
                max_batches=1,
                now=now,
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.list = AsyncMock(side_effect=[[base_row], []])
        self.service.update_with_row_version = AsyncMock(return_value=None)
        redact_summary = await self.service._phase_redact_due(
            tenant_id=self.tenant_id,
            dry_run=False,
            batch_size=10,
            max_batches=2,
            now=now,
        )
        self.assertEqual(redact_summary["RowsProcessed"], 0)

        self.service.list = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await self.service._phase_tombstone_expired(
                tenant_id=self.tenant_id,
                dry_run=False,
                batch_size=10,
                max_batches=1,
                now=now,
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.list = AsyncMock(return_value=[])
        tombstone_summary = await self.service._phase_tombstone_expired(
            tenant_id=self.tenant_id,
            dry_run=False,
            batch_size=10,
            max_batches=1,
            now=now,
        )
        self.assertEqual(tombstone_summary["RowsProcessed"], 0)

        self.service.list = AsyncMock(side_effect=[[base_row], []])
        self.service.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict(
                "audit_evidence_blob",
                {"id": base_row.id},
            )
        )
        tombstone_summary = await self.service._phase_tombstone_expired(
            tenant_id=self.tenant_id,
            dry_run=False,
            batch_size=10,
            max_batches=2,
            now=now,
        )
        self.assertEqual(tombstone_summary["RowsProcessed"], 0)

        self.service.list = AsyncMock(return_value=[base_row])
        self.service.update_with_row_version = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self.service._phase_tombstone_expired(
                tenant_id=self.tenant_id,
                dry_run=False,
                batch_size=10,
                max_batches=1,
                now=now,
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.list = AsyncMock(side_effect=[[base_row], []])
        self.service.update_with_row_version = AsyncMock(return_value=None)
        tombstone_summary = await self.service._phase_tombstone_expired(
            tenant_id=self.tenant_id,
            dry_run=False,
            batch_size=10,
            max_batches=2,
            now=now,
        )
        self.assertEqual(tombstone_summary["RowsProcessed"], 0)

        self.service.list = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await self.service._phase_purge_due(
                tenant_id=self.tenant_id,
                dry_run=False,
                batch_size=10,
                max_batches=1,
                now=now,
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.list = AsyncMock(side_effect=[[held_row], []])
        self.service.update_with_row_version = AsyncMock()
        purge_summary = await self.service._phase_purge_due(
            tenant_id=self.tenant_id,
            dry_run=False,
            batch_size=10,
            max_batches=2,
            now=now,
        )
        self.assertEqual(purge_summary["RowsProcessed"], 0)
        self.assertEqual(purge_summary["Batches"], 1)

        self.service.list = AsyncMock(side_effect=[[base_row], []])
        self.service.update_with_row_version = AsyncMock(
            side_effect=RowVersionConflict(
                "audit_evidence_blob",
                {"id": base_row.id},
            )
        )
        purge_summary = await self.service._phase_purge_due(
            tenant_id=self.tenant_id,
            dry_run=False,
            batch_size=10,
            max_batches=2,
            now=now,
        )
        self.assertEqual(purge_summary["RowsProcessed"], 0)

        self.service.list = AsyncMock(return_value=[base_row])
        self.service.update_with_row_version = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self.service._phase_purge_due(
                tenant_id=self.tenant_id,
                dry_run=False,
                batch_size=10,
                max_batches=1,
                now=now,
            )
        self.assertEqual(ctx.exception.code, 500)

        self.service.list = AsyncMock(side_effect=[[base_row], []])
        self.service.update_with_row_version = AsyncMock(return_value=None)
        purge_summary = await self.service._phase_purge_due(
            tenant_id=self.tenant_id,
            dry_run=False,
            batch_size=10,
            max_batches=2,
            now=now,
        )
        self.assertEqual(purge_summary["RowsProcessed"], 0)

    async def test_register_verify_hold_and_lifecycle_actions(self) -> None:
        register_payload = SimpleNamespace(
            tenant_id=self.tenant_id,
            trace_id="trace-1",
            source_plugin="com.vorsocomputing.mugen.audit",
            subject_namespace="ops.case",
            subject_id=uuid.uuid4(),
            storage_uri="s3://bucket/item-1",
            content_hash="DEADBEEF",
            hash_alg="sha256",
            content_length=32,
            immutability="immutable",
            retention_until=datetime.now(timezone.utc) + timedelta(days=1),
            redaction_due_at=datetime.now(timezone.utc) - timedelta(days=1),
            meta={"k": "v"},
        )

        created, status = await self.service.entity_set_action_register(
            auth_user_id=self.actor_id,
            data=register_payload,
        )
        self.assertEqual(status, 201)
        evidence_id = uuid.UUID(created["EvidenceBlobId"])

        existing, status = await self.service.action_register(
            tenant_id=self.tenant_id,
            where={"tenant_id": self.tenant_id},
            auth_user_id=self.actor_id,
            data=register_payload,
        )
        self.assertEqual((status, existing["EvidenceBlobId"]), (200, str(evidence_id)))

        row = self._find_row(evidence_id)
        verify_payload = SimpleNamespace(
            row_version=int(row["row_version"]),
            observed_hash="deadbeef",
            observed_hash_alg="sha256",
        )
        verify_result, status = await self.service.entity_action_verify_hash(
            entity_id=evidence_id,
            auth_user_id=self.actor_id,
            data=verify_payload,
        )
        self.assertEqual((status, verify_result["Verified"]), (200, True))

        row = self._find_row(evidence_id)
        verify_again = SimpleNamespace(
            row_version=int(row["row_version"]),
            observed_hash="deadbeef",
            observed_hash_alg="sha256",
        )
        verify_result, status = await self.service.action_verify_hash(
            tenant_id=self.tenant_id,
            entity_id=evidence_id,
            where={"tenant_id": self.tenant_id},
            auth_user_id=self.actor_id,
            data=verify_again,
        )
        self.assertEqual(
            (status, verify_result["VerificationStatus"]), (200, "verified")
        )

        row = self._find_row(evidence_id)
        failed_verify = SimpleNamespace(
            row_version=int(row["row_version"]),
            observed_hash="bad",
            observed_hash_alg="sha256",
        )
        verify_result, status = await self.service.entity_action_verify_hash(
            entity_id=evidence_id,
            auth_user_id=self.actor_id,
            data=failed_verify,
        )
        self.assertEqual((status, verify_result["VerificationStatus"]), (200, "failed"))

        hold_until = datetime.now(timezone.utc) + timedelta(days=2)
        row = self._find_row(evidence_id)
        place_hold = SimpleNamespace(
            row_version=int(row["row_version"]),
            reason="litigation",
            legal_hold_until=hold_until,
        )
        _, status = await self.service.entity_action_place_legal_hold(
            entity_id=evidence_id,
            auth_user_id=self.actor_id,
            data=place_hold,
        )
        self.assertEqual(status, 204)

        row = self._find_row(evidence_id)
        place_hold_same = SimpleNamespace(
            row_version=int(row["row_version"]),
            reason="litigation",
            legal_hold_until=hold_until,
        )
        _, status = await self.service.action_place_legal_hold(
            tenant_id=self.tenant_id,
            entity_id=evidence_id,
            where={"tenant_id": self.tenant_id},
            auth_user_id=self.actor_id,
            data=place_hold_same,
        )
        self.assertEqual(status, 204)

        row = self._find_row(evidence_id)
        with self.assertRaises(HTTPException) as ctx:
            await self.service.entity_action_place_legal_hold(
                entity_id=evidence_id,
                auth_user_id=self.actor_id,
                data=SimpleNamespace(
                    row_version=int(row["row_version"]),
                    reason="different",
                    legal_hold_until=hold_until + timedelta(days=1),
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

        row = self._find_row(evidence_id)
        _, status = await self.service.entity_action_release_legal_hold(
            entity_id=evidence_id,
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row["row_version"]),
                reason="resolved",
            ),
        )
        self.assertEqual(status, 204)

        row = self._find_row(evidence_id)
        _, status = await self.service.action_release_legal_hold(
            tenant_id=self.tenant_id,
            entity_id=evidence_id,
            where={"tenant_id": self.tenant_id},
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row["row_version"]),
                reason="already released",
            ),
        )
        self.assertEqual(status, 204)

        row = self._find_row(evidence_id)
        await self.service.entity_action_place_legal_hold(
            entity_id=evidence_id,
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row["row_version"]),
                reason="freeze",
                legal_hold_until=None,
            ),
        )
        row = self._find_row(evidence_id)
        with self.assertRaises(HTTPException) as ctx:
            await self.service.entity_action_redact(
                entity_id=evidence_id,
                auth_user_id=self.actor_id,
                data=SimpleNamespace(
                    row_version=int(row["row_version"]),
                    reason="pii",
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

        row = self._find_row(evidence_id)
        await self.service.entity_action_release_legal_hold(
            entity_id=evidence_id,
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row["row_version"]),
                reason="released",
            ),
        )

        row = self._find_row(evidence_id)
        _, status = await self.service.entity_action_redact(
            entity_id=evidence_id,
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row["row_version"]),
                reason="pii",
            ),
        )
        self.assertEqual(status, 204)

        row = self._find_row(evidence_id)
        _, status = await self.service.action_redact(
            tenant_id=self.tenant_id,
            entity_id=evidence_id,
            where={"tenant_id": self.tenant_id},
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row["row_version"]),
                reason="already",
            ),
        )
        self.assertEqual(status, 204)

        row = self._find_row(evidence_id)
        _, status = await self.service.entity_action_tombstone(
            entity_id=evidence_id,
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row["row_version"]),
                reason="expired",
                purge_after_days=2,
            ),
        )
        self.assertEqual(status, 204)

        row = self._find_row(evidence_id)
        _, status = await self.service.action_tombstone(
            tenant_id=self.tenant_id,
            entity_id=evidence_id,
            where={"tenant_id": self.tenant_id},
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row["row_version"]),
                reason="already",
                purge_after_days=2,
            ),
        )
        self.assertEqual(status, 204)

        row = self._find_row(evidence_id)
        _, status = await self.service.entity_action_purge(
            entity_id=evidence_id,
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row["row_version"]),
                reason="ttl",
            ),
        )
        self.assertEqual(status, 204)

        row = self._find_row(evidence_id)
        _, status = await self.service.action_purge(
            tenant_id=self.tenant_id,
            entity_id=evidence_id,
            where={"tenant_id": self.tenant_id},
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row["row_version"]),
                reason="already",
            ),
        )
        self.assertEqual(status, 204)

        self.assertGreaterEqual(self.audit_svc.create.await_count, 1)

    async def test_get_for_action_and_lifecycle_runner(self) -> None:
        now = datetime.now(timezone.utc)

        created_a, _ = await self.service.entity_set_action_register(
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                tenant_id=self.tenant_id,
                storage_uri="file://a",
                content_hash="a",
                hash_alg="sha256",
                immutability="immutable",
                retention_until=now - timedelta(days=2),
                redaction_due_at=now - timedelta(days=2),
                meta=None,
            ),
        )
        created_b, _ = await self.service.entity_set_action_register(
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                tenant_id=self.tenant_id,
                storage_uri="file://b",
                content_hash="b",
                hash_alg="sha256",
                immutability="immutable",
                retention_until=now - timedelta(days=2),
                redaction_due_at=now + timedelta(days=2),
                meta=None,
            ),
        )

        id_a = uuid.UUID(created_a["EvidenceBlobId"])
        id_b = uuid.UUID(created_b["EvidenceBlobId"])

        row_b = self._find_row(id_b)
        await self.service.entity_action_place_legal_hold(
            entity_id=id_b,
            auth_user_id=self.actor_id,
            data=SimpleNamespace(
                row_version=int(row_b["row_version"]),
                reason="hold",
                legal_hold_until=None,
            ),
        )

        dry_summary = await self.service.run_lifecycle(
            tenant_id=self.tenant_id,
            dry_run=True,
            batch_size=50,
            max_batches=3,
            now_override=now,
        )
        self.assertTrue(dry_summary["DryRun"])
        self.assertGreaterEqual(
            dry_summary["PhaseResults"]["redact_due"]["RowsPlanned"],
            1,
        )

        run_summary = await self.service.run_lifecycle(
            tenant_id=self.tenant_id,
            dry_run=False,
            batch_size=50,
            max_batches=3,
            now_override=now,
        )
        self.assertFalse(run_summary["DryRun"])

        row_a = self._find_row(id_a)
        row_b = self._find_row(id_b)
        self.assertIsNotNone(row_a["redacted_at"])
        self.assertIsNotNone(row_a["tombstoned_at"])
        self.assertIsNotNone(row_a["purged_at"])
        self.assertIsNone(row_b.get("purged_at"))

        with self.assertRaises(HTTPException) as ctx:
            await self.service._get_for_action(
                where={"id": uuid.uuid4()},
                expected_row_version=1,
                not_found="missing",
            )
        self.assertEqual(ctx.exception.code, 404)

        row_a = self._find_row(id_a)
        with self.assertRaises(HTTPException) as ctx:
            await self.service._get_for_action(
                where={"id": id_a},
                expected_row_version=int(row_a["row_version"]) - 1,
                not_found="missing",
            )
        self.assertEqual(ctx.exception.code, 409)

        self.service.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await self.service._get_for_action(
                where={"id": id_a},
                expected_row_version=int(row_a["row_version"]),
                not_found="missing",
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_register_rejects_invalid_immutability(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self.service.entity_set_action_register(
                auth_user_id=self.actor_id,
                data=SimpleNamespace(
                    tenant_id=self.tenant_id,
                    storage_uri="s3://bucket/x",
                    content_hash="abc",
                    hash_alg="sha256",
                    immutability="invalid",
                ),
            )
        self.assertEqual(ctx.exception.code, 400)
