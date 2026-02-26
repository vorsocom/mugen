"""Audit service tests for hash chain and lifecycle behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid
from unittest.mock import patch

from quart import Quart


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
from mugen.core.contract.gateway.storage.rdbms.types import (  # noqa: E402
    FilterGroup,
    RowVersionConflict,
    ScalarFilterOp,
)
from mugen.core.plugin.audit.service.audit_event import AuditEventService  # noqa: E402


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None, **_kwargs):
    raise _AbortCalled(code, message)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class _KeyRefService:
    def __init__(self, key_id: str, secret: bytes):
        self._key_id = key_id
        self._secret = secret
        self.purpose_calls: list[dict[str, object]] = []
        self.key_id_calls: list[dict[str, object]] = []

    async def resolve_secret_for_purpose(
        self,
        *,
        tenant_id: uuid.UUID | None,
        purpose: str,
    ):
        self.purpose_calls.append(
            {
                "tenant_id": tenant_id,
                "purpose": purpose,
            }
        )
        return SimpleNamespace(
            key_id=self._key_id,
            secret=self._secret,
            provider="local",
        )

    async def resolve_secret_for_key_id(
        self,
        *,
        tenant_id: uuid.UUID | None,
        purpose: str,
        key_id: str,
    ):
        self.key_id_calls.append(
            {
                "tenant_id": tenant_id,
                "purpose": purpose,
                "key_id": key_id,
            }
        )
        if key_id.strip().lower() != self._key_id.strip().lower():
            return None
        return SimpleNamespace(
            key_id=self._key_id,
            secret=self._secret,
            provider="local",
        )


class _Registry:
    def __init__(self, key_ref_service: _KeyRefService):
        self._key_ref_service = key_ref_service

    def get_resource(self, name: str):
        if name != "KeyRefs":
            raise KeyError(name)
        return SimpleNamespace(service_key=name)

    def get_edm_service(self, service_key: str):
        if service_key != "KeyRefs":
            raise KeyError(service_key)
        return self._key_ref_service


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
        self.tables = {
            "audit_event": [],
            "audit_chain_head": [],
        }

    @asynccontextmanager
    async def unit_of_work(self):
        yield _FakeUow(self)

    @staticmethod
    def _matches(row: dict, where: dict) -> bool:
        return all(row.get(key) == value for key, value in where.items())

    def _insert_row(self, table: str, record: dict) -> dict:
        now = _now_utc()
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
            row["updated_at"] = _now_utc()
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
            value = row.get(scalar.field)
            if not cls._scalar_match(value, scalar.op, scalar.value):
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


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        audit=SimpleNamespace(
            lifecycle=SimpleNamespace(
                purge_grace_days=7,
                batch_size_default=50,
            ),
            hash_chain=SimpleNamespace(
                active_key_id="default",
                keys={"default": "unit-test-secret"},
            ),
            emit=SimpleNamespace(fail_closed=False),
        )
    )


class TestAuditServiceLifecycleAndChain(unittest.IsolatedAsyncioTestCase):
    """Covers chain creation, verification, and lifecycle action behavior."""

    async def asyncSetUp(self) -> None:
        self.gateway = _FakeRsg()
        self.service = AuditEventService(
            table="audit_event",
            rsg=self.gateway,
            config_provider=_config,
        )

    async def _create_event(self, **overrides):
        payload = {
            "tenant_id": overrides.get("tenant_id"),
            "actor_id": uuid.uuid4(),
            "entity_set": overrides.get("entity_set", "Users"),
            "entity": overrides.get("entity", "User"),
            "entity_id": overrides.get("entity_id", uuid.uuid4()),
            "operation": overrides.get("operation", "update"),
            "action_name": overrides.get("action_name"),
            "occurred_at": overrides.get("occurred_at", _now_utc()),
            "outcome": overrides.get("outcome", "success"),
            "request_id": overrides.get("request_id", "req-1"),
            "correlation_id": overrides.get("correlation_id", "corr-1"),
            "source_plugin": overrides.get("source_plugin", "com.test.audit"),
            "changed_fields": overrides.get("changed_fields", ["display_name"]),
            "before_snapshot": overrides.get("before_snapshot", {"v": "before"}),
            "after_snapshot": overrides.get("after_snapshot", {"v": "after"}),
            "meta": overrides.get("meta", {"phase": "unit"}),
            "retention_until": overrides.get(
                "retention_until",
                _now_utc() + timedelta(days=30),
            ),
            "redaction_due_at": overrides.get(
                "redaction_due_at",
                _now_utc() + timedelta(days=7),
            ),
            "redacted_at": overrides.get("redacted_at"),
            "redaction_reason": overrides.get("redaction_reason"),
        }
        return await self.service.create(payload)

    async def test_create_assigns_scope_sequence_and_hash(self):
        first = await self._create_event(entity_set="Users", tenant_id=None)
        second = await self._create_event(entity_set="Users", tenant_id=None)

        self.assertEqual(first.scope_seq, 1)
        self.assertEqual(second.scope_seq, 2)
        self.assertEqual(second.prev_entry_hash, first.entry_hash)
        self.assertTrue(first.entry_hash)
        self.assertTrue(second.entry_hash)
        self.assertEqual(first.scope_key, second.scope_key)

        head = self.gateway.tables["audit_chain_head"][0]
        self.assertEqual(head["last_seq"], 2)
        self.assertEqual(head["last_entry_hash"], second.entry_hash)

    async def test_verify_chain_and_tamper_detection(self):
        created = await self._create_event(entity_set="Users", tenant_id=None)

        summary, status = await self.service.entity_set_action_verify_chain(
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                from_occurred_at=None,
                to_occurred_at=None,
                max_rows=100,
                require_clean=False,
            ),
        )
        self.assertEqual(status, 200)
        self.assertTrue(summary["IsValid"])

        self.gateway.tables["audit_event"][0]["operation"] = "tampered"
        dirty, status = await self.service.entity_set_action_verify_chain(
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                from_occurred_at=None,
                to_occurred_at=None,
                max_rows=100,
                require_clean=False,
            ),
        )
        self.assertEqual(status, 200)
        self.assertFalse(dirty["IsValid"])
        self.assertGreater(dirty["MismatchCount"], 0)

        with patch(
            "mugen.core.plugin.audit.service.audit_event.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.entity_set_action_verify_chain(
                    auth_user_id=uuid.uuid4(),
                    data=SimpleNamespace(
                        from_occurred_at=None,
                        to_occurred_at=None,
                        max_rows=100,
                        require_clean=True,
                    ),
                )
            self.assertEqual(ex.exception.code, 409)
        self.assertIsNotNone(created.entry_hash)

    async def test_verify_chain_with_keyrefs_only_secret_resolution(self):
        tenant_id = uuid.uuid4()
        key_ref_service = _KeyRefService(
            key_id="tenant-chain-key-1",
            secret=b"tenant-chain-secret",
        )
        service = AuditEventService(
            table="audit_event",
            rsg=self.gateway,
            config_provider=lambda: SimpleNamespace(
                audit=SimpleNamespace(
                    lifecycle=SimpleNamespace(
                        purge_grace_days=7,
                        batch_size_default=50,
                    ),
                    hash_chain=SimpleNamespace(
                        active_key_id="not-used",
                        keys={},
                    ),
                    emit=SimpleNamespace(fail_closed=False),
                )
            ),
            registry_provider=lambda: _Registry(key_ref_service),
        )
        now = _now_utc()
        created = await service.create(
            {
                "tenant_id": tenant_id,
                "actor_id": uuid.uuid4(),
                "entity_set": "Users",
                "entity": "User",
                "entity_id": uuid.uuid4(),
                "operation": "create",
                "action_name": "create",
                "occurred_at": now,
                "outcome": "success",
                "request_id": "req-keyref-only",
                "correlation_id": "corr-keyref-only",
                "source_plugin": "com.test.audit",
                "changed_fields": ["email"],
                "before_snapshot": None,
                "after_snapshot": {"email": "x@example.com"},
                "meta": {"case": "keyrefs-only"},
                "retention_until": now + timedelta(days=30),
                "redaction_due_at": now + timedelta(days=7),
            }
        )
        self.assertEqual(created.hash_key_id, "tenant-chain-key-1")

        summary, status = await service.action_verify_chain(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                from_occurred_at=None,
                to_occurred_at=None,
                max_rows=100,
                require_clean=False,
            ),
        )
        self.assertEqual(status, 200)
        self.assertTrue(summary["IsValid"])
        self.assertEqual(summary["MismatchCount"], 0)
        self.assertGreaterEqual(len(key_ref_service.purpose_calls), 1)
        self.assertEqual(len(key_ref_service.key_id_calls), 1)
        self.assertEqual(
            key_ref_service.key_id_calls[0]["tenant_id"],
            tenant_id,
        )

    async def test_redact_and_legal_hold_conflict(self):
        event = await self._create_event()
        before_hash = event.before_snapshot_hash
        after_hash = event.after_snapshot_hash

        _, status = await self.service.entity_action_redact(
            entity_id=event.id,
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(row_version=event.row_version, reason="pii-redact"),
        )
        self.assertEqual(status, 204)

        stored = self.gateway.tables["audit_event"][0]
        self.assertIsNone(stored["before_snapshot"])
        self.assertIsNone(stored["after_snapshot"])
        self.assertEqual(stored["before_snapshot_hash"], before_hash)
        self.assertEqual(stored["after_snapshot_hash"], after_hash)
        self.assertIsNotNone(stored["redacted_at"])

        held = await self._create_event(entity_set="Users")
        _, status = await self.service.entity_action_place_legal_hold(
            entity_id=held.id,
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                row_version=held.row_version,
                reason="litigation",
                legal_hold_until=None,
            ),
        )
        self.assertEqual(status, 204)

        held_row = self.gateway.tables["audit_event"][1]
        with patch(
            "mugen.core.plugin.audit.service.audit_event.abort",
            side_effect=_abort_raiser,
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await self.service.entity_action_redact(
                    entity_id=held.id,
                    auth_user_id=uuid.uuid4(),
                    data=SimpleNamespace(
                        row_version=held_row["row_version"],
                        reason="blocked-by-hold",
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

    async def test_place_release_hold_and_tombstone_idempotency(self):
        event = await self._create_event()
        actor_id = uuid.uuid4()

        _, status = await self.service.entity_action_place_legal_hold(
            entity_id=event.id,
            auth_user_id=actor_id,
            data=SimpleNamespace(
                row_version=event.row_version,
                reason="regulatory",
                legal_hold_until=None,
            ),
        )
        self.assertEqual(status, 204)

        row = self.gateway.tables["audit_event"][0]
        _, status = await self.service.entity_action_place_legal_hold(
            entity_id=event.id,
            auth_user_id=actor_id,
            data=SimpleNamespace(
                row_version=row["row_version"],
                reason="regulatory",
                legal_hold_until=None,
            ),
        )
        self.assertEqual(status, 204)

        _, status = await self.service.entity_action_release_legal_hold(
            entity_id=event.id,
            auth_user_id=actor_id,
            data=SimpleNamespace(
                row_version=row["row_version"],
                reason="release",
            ),
        )
        self.assertEqual(status, 204)

        row = self.gateway.tables["audit_event"][0]
        _, status = await self.service.entity_action_release_legal_hold(
            entity_id=event.id,
            auth_user_id=actor_id,
            data=SimpleNamespace(
                row_version=row["row_version"],
                reason="already-released",
            ),
        )
        self.assertEqual(status, 204)

        _, status = await self.service.entity_action_tombstone(
            entity_id=event.id,
            auth_user_id=actor_id,
            data=SimpleNamespace(
                row_version=row["row_version"],
                reason="retention-expired",
                purge_after_days=3,
            ),
        )
        self.assertEqual(status, 204)
        row = self.gateway.tables["audit_event"][0]
        self.assertIsNotNone(row["tombstoned_at"])
        self.assertIsNotNone(row["purge_due_at"])

    async def test_run_lifecycle_and_seal_backlog_paths(self):
        old_time = _now_utc() - timedelta(days=10)
        run_now = _now_utc()
        redact_event = await self._create_event(
            redaction_due_at=old_time,
            retention_until=_now_utc() + timedelta(days=10),
        )
        tombstone_event = await self._create_event(
            redaction_due_at=_now_utc() + timedelta(days=10),
            retention_until=old_time,
        )

        summary, status = await self.service.entity_set_action_run_lifecycle(
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                batch_size=100,
                max_batches=3,
                dry_run=False,
                now_override=run_now,
                purge_grace_days_override=5,
                phases=["redact_due", "tombstone_expired"],
            ),
        )
        self.assertEqual(status, 200)
        self.assertGreater(summary["TotalProcessed"], 0)

        by_id = {str(row["id"]): row for row in self.gateway.tables["audit_event"]}
        self.assertIsNotNone(by_id[str(redact_event.id)]["redacted_at"])
        self.assertIsNotNone(by_id[str(tombstone_event.id)]["tombstoned_at"])
        self.assertEqual(
            by_id[str(tombstone_event.id)]["purge_due_at"],
            run_now + timedelta(days=5),
        )

        rerun, status = await self.service.entity_set_action_run_lifecycle(
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                batch_size=100,
                max_batches=1,
                dry_run=False,
                now_override=run_now,
                purge_grace_days_override=5,
                phases=["redact_due", "tombstone_expired"],
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(rerun["TotalProcessed"], 0)

        backlog_row = self.gateway.tables["audit_event"][0]
        backlog_row["scope_seq"] = None
        backlog_row["prev_entry_hash"] = None
        backlog_row["entry_hash"] = None
        backlog_row["sealed_at"] = None
        backlog_row["row_version"] = int(backlog_row["row_version"]) + 1

        sealed, status = await self.service.entity_set_action_seal_backlog(
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(batch_size=10, max_batches=2),
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(sealed["RowsSealed"], 1)
        self.assertEqual(sealed["RemainingCount"], 0)
        self.assertIsNotNone(self.gateway.tables["audit_event"][0]["entry_hash"])

    async def test_tenant_and_non_tenant_action_variants(self):
        tenant_id = uuid.uuid4()
        tenant_event = await self._create_event(tenant_id=tenant_id)
        app = Quart("audit-tenant-action")

        async with app.test_request_context("/"):
            _, status = await self.service.action_place_legal_hold(
                tenant_id=tenant_id,
                entity_id=tenant_event.id,
                where={"tenant_id": tenant_id, "id": tenant_event.id},
                auth_user_id=uuid.uuid4(),
                data=SimpleNamespace(
                    row_version=tenant_event.row_version,
                    reason="tenant-hold",
                    legal_hold_until=None,
                ),
            )
        self.assertEqual(status, 204)
