"""Unit tests for ops_governance phase4 legal-hold and lifecycle orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

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
from mugen.core.plugin.ops_governance.model.legal_hold import LegalHold
from mugen.core.plugin.ops_governance.model.lifecycle_action_log import (
    LifecycleActionLog,
)
from mugen.core.plugin.ops_governance.domain import (
    LegalHoldDE,
    RetentionClassDE,
    RetentionPolicyDE,
)
from mugen.core.plugin.ops_governance.service import legal_hold as legal_hold_mod
from mugen.core.plugin.ops_governance.service import (
    retention_policy as retention_policy_mod,
)
from mugen.core.plugin.ops_governance.service.legal_hold import LegalHoldService
from mugen.core.plugin.ops_governance.service.retention_policy import (
    RetentionPolicyService,
)


class _Registry:
    def __init__(self, **services):
        self._services = services

    def get_resource(self, name: str):
        return SimpleNamespace(service_key=name)

    def get_edm_service(self, service_key: str):
        return self._services[service_key]


class TestOpsGovernancePhase4Services(unittest.IsolatedAsyncioTestCase):
    """Covers legal hold orchestration and retention run_lifecycle branches."""

    async def test_legal_hold_service_paths(self) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        hold_id = uuid.uuid4()
        resource_id = uuid.uuid4()

        with patch.object(
            legal_hold_mod.di,
            "container",
            new=SimpleNamespace(
                get_required_ext_service=lambda _key: "registry-service",
            ),
        ):
            self.assertEqual(legal_hold_mod._registry_provider(), "registry-service")

        audit_events = Mock()
        audit_events.get = AsyncMock(return_value=SimpleNamespace(id=resource_id))
        audit_events.update = AsyncMock(return_value=SimpleNamespace(id=resource_id))

        evidence_blobs = Mock()
        evidence_blobs.get = AsyncMock(return_value=SimpleNamespace(id=resource_id))
        evidence_blobs.update = AsyncMock(return_value=SimpleNamespace(id=resource_id))

        svc = LegalHoldService(
            table="ops_governance_legal_hold",
            rsg=Mock(),
            registry_provider=lambda: _Registry(
                AuditEvents=audit_events,
                EvidenceBlobs=evidence_blobs,
            ),
        )
        self.assertIsNone(svc._normalize_optional_text(None))
        self.assertEqual(svc._normalize_optional_text(" value "), "value")
        with self.assertRaises(HTTPException) as ctx:
            svc._normalize_required_text(" ", field_name="Reason")
        self.assertEqual(ctx.exception.code, 400)

        svc._lifecycle_log_service.create = AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        svc.get = AsyncMock(return_value=None)
        placed_hold = LegalHoldDE(
            id=hold_id,
            tenant_id=tenant_id,
            resource_type="audit_event",
            resource_id=resource_id,
            status="active",
            row_version=1,
        )
        svc.create = AsyncMock(return_value=placed_hold)

        response, status = await svc.action_place_hold(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=actor_id,
            data=SimpleNamespace(
                resource_type="audit_event",
                resource_id=resource_id,
                reason="litigation",
                hold_until=None,
                retention_class_id=None,
                attributes={"case": "x"},
            ),
        )
        self.assertEqual((status, response["Status"]), (201, "active"))
        audit_events.update.assert_awaited()

        svc.get = AsyncMock(return_value=placed_hold)
        updated_hold = LegalHoldDE(
            id=hold_id,
            tenant_id=tenant_id,
            resource_type="audit_event",
            resource_id=resource_id,
            status="active",
            row_version=2,
        )
        svc.update = AsyncMock(return_value=updated_hold)
        response, status = await svc.action_place_hold(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=actor_id,
            data=SimpleNamespace(
                resource_type="audit_event",
                resource_id=resource_id,
                reason="updated",
                hold_until=None,
                retention_class_id=None,
                attributes=None,
            ),
        )
        self.assertEqual((status, response["Status"]), (200, "active"))

        svc._get_for_action = AsyncMock(
            return_value=LegalHoldDE(
                id=hold_id,
                tenant_id=tenant_id,
                resource_type="audit_event",
                resource_id=resource_id,
                status="active",
                row_version=2,
            )
        )
        released = LegalHoldDE(
            id=hold_id,
            tenant_id=tenant_id,
            resource_type="audit_event",
            resource_id=resource_id,
            status="released",
            row_version=3,
        )
        svc.update_with_row_version = AsyncMock(return_value=released)

        response, status = await svc.action_release_hold(
            tenant_id=tenant_id,
            entity_id=hold_id,
            where={"tenant_id": tenant_id, "id": hold_id},
            auth_user_id=actor_id,
            data=SimpleNamespace(row_version=2, reason="case closed"),
        )
        self.assertEqual((status, response["Status"]), (200, "released"))

        svc._get_for_action = AsyncMock(return_value=released)
        response, status = await svc.action_release_hold(
            tenant_id=tenant_id,
            entity_id=hold_id,
            where={"tenant_id": tenant_id, "id": hold_id},
            auth_user_id=actor_id,
            data=SimpleNamespace(row_version=3, reason="already"),
        )
        self.assertEqual((status, response["Status"]), (200, "released"))

        self.assertEqual(svc._normalize_resource_type("audit"), "audit_event")
        self.assertEqual(svc._normalize_resource_type("EvidenceBlob"), "evidence_blob")
        with self.assertRaises(HTTPException) as ctx:
            svc._normalize_resource_type("unknown")
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_place_hold(
                tenant_id=tenant_id,
                where={},
                auth_user_id=actor_id,
                data=SimpleNamespace(
                    resource_type="audit_event",
                    resource_id="not-uuid",
                    reason="bad",
                ),
            )
        self.assertEqual(ctx.exception.code, 400)

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_place_hold(
                tenant_id=tenant_id,
                where={},
                auth_user_id=actor_id,
                data=SimpleNamespace(
                    resource_type="audit_event",
                    resource_id=resource_id,
                    reason="bad",
                ),
            )
        self.assertEqual(ctx.exception.code, 500)

        svc_branch = LegalHoldService(
            table="ops_governance_legal_hold",
            rsg=Mock(),
            registry_provider=lambda: _Registry(
                AuditEvents=audit_events,
                EvidenceBlobs=evidence_blobs,
            ),
        )
        svc_branch.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc_branch._get_for_action(
                where={"tenant_id": tenant_id, "id": hold_id},
                expected_row_version=1,
            )
        self.assertEqual(ctx.exception.code, 404)

        svc_branch.get = AsyncMock(
            side_effect=[None, LegalHoldDE(id=hold_id, tenant_id=tenant_id)]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc_branch._get_for_action(
                where={"tenant_id": tenant_id, "id": hold_id},
                expected_row_version=1,
            )
        self.assertEqual(ctx.exception.code, 409)

        svc_branch.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc_branch._get_for_action(
                where={"tenant_id": tenant_id, "id": hold_id},
                expected_row_version=1,
            )
        self.assertEqual(ctx.exception.code, 500)

        svc_branch.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
        with self.assertRaises(HTTPException) as ctx:
            await svc_branch._get_for_action(
                where={"tenant_id": tenant_id, "id": hold_id},
                expected_row_version=1,
            )
        self.assertEqual(ctx.exception.code, 500)

        expected = LegalHoldDE(id=hold_id, tenant_id=tenant_id, row_version=7)
        svc_branch.get = AsyncMock(return_value=expected)
        current = await svc_branch._get_for_action(
            where={"tenant_id": tenant_id, "id": hold_id},
            expected_row_version=7,
        )
        self.assertEqual(current.id, hold_id)

        audit_events.get = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._sync_hold_state(
                tenant_id=tenant_id,
                resource_type="audit_event",
                resource_id=resource_id,
                active=True,
                hold_until=None,
                user_id=actor_id,
                reason="x",
            )
        self.assertEqual(ctx.exception.code, 404)

        evidence_blobs.get = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._sync_hold_state(
                tenant_id=tenant_id,
                resource_type="evidence_blob",
                resource_id=resource_id,
                active=True,
                hold_until=None,
                user_id=actor_id,
                reason="x",
            )
        self.assertEqual(ctx.exception.code, 404)

        evidence_blobs.get = AsyncMock(return_value=SimpleNamespace(id=resource_id))
        evidence_blobs.update = AsyncMock(return_value=SimpleNamespace(id=resource_id))
        await svc._sync_hold_state(
            tenant_id=tenant_id,
            resource_type="evidence_blob",
            resource_id=resource_id,
            active=True,
            hold_until=None,
            user_id=actor_id,
            reason="hold",
        )
        await svc._sync_hold_state(
            tenant_id=tenant_id,
            resource_type="evidence_blob",
            resource_id=resource_id,
            active=False,
            hold_until=None,
            user_id=actor_id,
            reason="release",
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc._sync_hold_state(
                tenant_id=tenant_id,
                resource_type="other",
                resource_id=resource_id,
                active=True,
                hold_until=None,
                user_id=actor_id,
                reason="x",
            )
        self.assertEqual(ctx.exception.code, 400)

        svc._get_for_action = AsyncMock(
            return_value=LegalHoldDE(
                id=hold_id,
                tenant_id=tenant_id,
                resource_type="audit_event",
                resource_id=resource_id,
                status="active",
                row_version=2,
            )
        )
        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_release_hold(
                tenant_id=tenant_id,
                entity_id=hold_id,
                where={"tenant_id": tenant_id, "id": hold_id},
                auth_user_id=actor_id,
                data=SimpleNamespace(row_version=2, reason="x"),
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_release_hold(
                tenant_id=tenant_id,
                entity_id=hold_id,
                where={"tenant_id": tenant_id, "id": hold_id},
                auth_user_id=actor_id,
                data=SimpleNamespace(row_version=2, reason="x"),
            )
        self.assertEqual(ctx.exception.code, 409)

        self.assertEqual(
            LegalHold.__repr__(SimpleNamespace(id=hold_id)),
            f"LegalHold(id={hold_id!r})",
        )
        self.assertEqual(
            LifecycleActionLog.__repr__(SimpleNamespace(id=hold_id)),
            f"LifecycleActionLog(id={hold_id!r})",
        )

    async def test_retention_policy_run_lifecycle_paths(self) -> None:
        tenant_id = uuid.uuid4()
        policy_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        now = datetime(2026, 2, 26, 0, 0, tzinfo=timezone.utc)

        audit_rows = [
            SimpleNamespace(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                occurred_at=now,
                created_at=now,
                retention_until=None,
            )
        ]
        evidence_rows = [
            SimpleNamespace(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                occurred_at=None,
                created_at=now,
                retention_until=None,
            )
        ]

        audit_service = Mock()
        audit_service.list = AsyncMock(side_effect=[audit_rows, []])
        audit_service.update = AsyncMock(
            return_value=SimpleNamespace(id=audit_rows[0].id)
        )
        audit_service.action_run_lifecycle = AsyncMock(
            return_value=({"TotalProcessed": 1}, 200)
        )

        evidence_service = Mock()
        evidence_service.list = AsyncMock(side_effect=[evidence_rows, []])
        evidence_service.update = AsyncMock(
            return_value=SimpleNamespace(id=evidence_rows[0].id)
        )
        evidence_service.run_lifecycle = AsyncMock(return_value={"RowsProcessed": 1})

        registry = _Registry(AuditEvents=audit_service, EvidenceBlobs=evidence_service)

        svc = RetentionPolicyService(
            table="ops_governance_retention_policy",
            rsg=Mock(),
            registry_provider=lambda: registry,
        )
        with patch.object(
            retention_policy_mod.di,
            "container",
            new=SimpleNamespace(
                get_required_ext_service=lambda _key: "registry-service",
            ),
        ):
            self.assertEqual(
                retention_policy_mod._registry_provider(), "registry-service"
            )
        svc._now_utc = lambda: now
        svc._lifecycle_log_service.create = AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4())
        )

        active_policy = RetentionPolicyDE(
            id=policy_id,
            tenant_id=tenant_id,
            code="ops-retention",
            is_active=True,
            row_version=4,
        )
        svc.get = AsyncMock(return_value=active_policy)
        svc.update_with_row_version = AsyncMock(return_value=active_policy)
        svc._retention_class_service.list = AsyncMock(
            return_value=[
                RetentionClassDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    code="audit-default",
                    name="Audit Default",
                    resource_type="audit_event",
                    retention_days=30,
                    redaction_after_days=7,
                    is_active=True,
                ),
                RetentionClassDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    code="evidence-default",
                    name="Evidence Default",
                    resource_type="evidence_blob",
                    retention_days=60,
                    redaction_after_days=None,
                    is_active=True,
                ),
            ]
        )

        summary, status = await svc.action_run_lifecycle(
            tenant_id=tenant_id,
            entity_id=policy_id,
            where={"tenant_id": tenant_id, "id": policy_id},
            auth_user_id=actor_id,
            data=SimpleNamespace(
                row_version=4,
                dry_run=False,
                batch_size=100,
                max_batches=2,
                now_override=now,
            ),
        )
        self.assertEqual(status, 200)
        self.assertFalse(summary["DryRun"])
        self.assertIn("audit_event", summary["ClassMarking"])
        self.assertIn("evidence_blob", summary["ClassMarking"])
        self.assertEqual(svc._lifecycle_log_service.create.await_count, 1)

        summary, status = await svc.action_run_lifecycle(
            tenant_id=tenant_id,
            entity_id=policy_id,
            where={"tenant_id": tenant_id, "id": policy_id},
            auth_user_id=actor_id,
            data=SimpleNamespace(
                row_version=4,
                dry_run=True,
                batch_size=100,
                max_batches=2,
                now_override=now,
            ),
        )
        self.assertEqual(status, 200)
        self.assertTrue(summary["DryRun"])

        inactive_policy = RetentionPolicyDE(
            id=policy_id,
            tenant_id=tenant_id,
            code="ops-retention",
            is_active=False,
            row_version=4,
        )
        svc.get = AsyncMock(return_value=inactive_policy)
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_run_lifecycle(
                tenant_id=tenant_id,
                entity_id=policy_id,
                where={"tenant_id": tenant_id, "id": policy_id},
                auth_user_id=actor_id,
                data=SimpleNamespace(
                    row_version=4,
                    dry_run=False,
                    batch_size=100,
                    max_batches=2,
                    now_override=now,
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

        self.assertEqual(svc._normalize_resource_type("audit"), "audit_event")
        self.assertEqual(svc._normalize_resource_type("EvidenceBlob"), "evidence_blob")
        with self.assertRaises(HTTPException) as ctx:
            svc._normalize_resource_type("unsupported")
        self.assertEqual(ctx.exception.code, 400)

        svc._retention_class_service.list = AsyncMock(
            side_effect=SQLAlchemyError("boom")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._active_retention_classes(tenant_id=tenant_id)
        self.assertEqual(ctx.exception.code, 500)

        empty_result = await svc._apply_class_defaults(
            tenant_id=tenant_id,
            retention_class=RetentionClassDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                code="audit-default",
                name="Audit",
                resource_type="audit_event",
                retention_days=1,
                redaction_after_days=1,
                is_active=True,
            ),
            dry_run=False,
            batch_size=50,
            max_batches=0,
        )
        self.assertEqual(empty_result["MarkedRetentionUntil"], 0)

        svc._resource_service = AsyncMock(return_value=audit_service)
        audit_service.list = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._apply_class_defaults(
                tenant_id=tenant_id,
                retention_class=RetentionClassDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    code="audit-default",
                    name="Audit",
                    resource_type="audit_event",
                    retention_days=1,
                    redaction_after_days=1,
                    is_active=True,
                ),
                dry_run=False,
                batch_size=50,
                max_batches=1,
            )
        self.assertEqual(ctx.exception.code, 500)

        no_base_row = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            occurred_at=None,
            created_at=None,
            retention_until=None,
        )
        audit_service.list = AsyncMock(side_effect=[[no_base_row], []])
        audit_service.update = AsyncMock(return_value=None)
        result = await svc._apply_class_defaults(
            tenant_id=tenant_id,
            retention_class=RetentionClassDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                code="audit-default",
                name="Audit",
                resource_type="audit_event",
                retention_days=1,
                redaction_after_days=1,
                is_active=True,
            ),
            dry_run=False,
            batch_size=50,
            max_batches=2,
        )
        self.assertEqual(result["MarkedRetentionUntil"], 0)

        no_update_row = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            occurred_at=now,
            created_at=now,
            retention_until=None,
        )
        audit_service.list = AsyncMock(side_effect=[[no_update_row], []])
        audit_service.update = AsyncMock(return_value=None)
        result = await svc._apply_class_defaults(
            tenant_id=tenant_id,
            retention_class=RetentionClassDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                code="audit-default",
                name="Audit",
                resource_type="audit_event",
                retention_days=1,
                redaction_after_days=1,
                is_active=True,
            ),
            dry_run=False,
            batch_size=50,
            max_batches=2,
        )
        self.assertEqual(result["MarkedRetentionUntil"], 0)

        good_row = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            occurred_at=now,
            created_at=now,
            retention_until=None,
        )
        audit_service.list = AsyncMock(side_effect=[[good_row], []])
        audit_service.update = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._apply_class_defaults(
                tenant_id=tenant_id,
                retention_class=RetentionClassDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    code="audit-default",
                    name="Audit",
                    resource_type="audit_event",
                    retention_days=1,
                    redaction_after_days=1,
                    is_active=True,
                ),
                dry_run=False,
                batch_size=50,
                max_batches=2,
            )
        self.assertEqual(ctx.exception.code, 500)

        fresh_dry_row = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            occurred_at=now,
            created_at=now,
            retention_until=None,
        )
        audit_service.list = AsyncMock(side_effect=[[fresh_dry_row], []])
        dry_marking = await svc._apply_class_defaults(
            tenant_id=tenant_id,
            retention_class=RetentionClassDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                code="audit-default",
                name="Audit",
                resource_type="audit_event",
                retention_days=1,
                redaction_after_days=1,
                is_active=True,
            ),
            dry_run=True,
            batch_size=1,
            max_batches=2,
        )
        self.assertGreaterEqual(dry_marking["MarkedRetentionUntil"], 1)

        evidence_row = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            occurred_at=now,
            created_at=now,
            retention_until=None,
        )
        evidence_defaults_service = Mock()
        evidence_defaults_service.list = AsyncMock(side_effect=[[evidence_row], []])
        evidence_defaults_service.update = AsyncMock(return_value=evidence_row)
        svc._resource_service = AsyncMock(return_value=evidence_defaults_service)

        no_redaction_marking = await svc._apply_class_defaults(
            tenant_id=tenant_id,
            retention_class=RetentionClassDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                code="evidence-default",
                name="Evidence",
                resource_type="evidence_blob",
                retention_days=2,
                redaction_after_days=None,
                is_active=True,
            ),
            dry_run=True,
            batch_size=1,
            max_batches=1,
        )
        self.assertGreaterEqual(no_redaction_marking["MarkedRetentionUntil"], 0)

        svc._retention_class_service.list = AsyncMock(
            return_value=[
                RetentionClassDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    code="audit-only",
                    name="Audit Only",
                    resource_type="audit_event",
                    retention_days=30,
                    redaction_after_days=7,
                    is_active=True,
                )
            ]
        )
        audit_service.list = AsyncMock(return_value=[])
        svc._resource_service = AsyncMock(
            side_effect=(
                lambda resource_name: (
                    audit_service
                    if resource_name == "AuditEvents"
                    else evidence_service
                )
            )
        )
        svc.get = AsyncMock(return_value=active_policy)
        summary, status = await svc.action_run_lifecycle(
            tenant_id=tenant_id,
            entity_id=policy_id,
            where={"tenant_id": tenant_id, "id": policy_id},
            auth_user_id=actor_id,
            data=SimpleNamespace(
                row_version=4,
                dry_run=True,
                batch_size=100,
                max_batches=1,
                now_override=now,
            ),
        )
        self.assertEqual(status, 200)
        self.assertNotIn("evidence_blob", summary["ClassMarking"])
