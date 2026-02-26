"""Focused behavior tests for ops_reporting ExportJobService actions."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.ops_reporting.api.validation import (
    ExportJobBuildValidation,
    ExportJobCreateValidation,
    ExportJobVerifyValidation,
)
from mugen.core.plugin.ops_reporting.domain import ExportJobDE, ExportItemDE
from mugen.core.plugin.ops_reporting.service import export_job as export_job_mod
from mugen.core.plugin.ops_reporting.service.export_job import ExportJobService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


class TestMugenOpsReportingExportJobService(unittest.IsolatedAsyncioTestCase):
    """Covers create/build/verify behavior for export-job actions."""

    def test_registry_provider_uses_admin_registry_ext_service(self) -> None:
        mocked = Mock(return_value="registry-service")
        with patch.object(
            export_job_mod.di,
            "container",
            new=SimpleNamespace(get_required_ext_service=mocked),
        ):
            resolved = export_job_mod._registry_provider()

        self.assertEqual(resolved, "registry-service")
        mocked.assert_called_once_with(export_job_mod.di.EXT_SERVICE_ADMIN_REGISTRY)

    def _build_ready_service(
        self,
        *,
        tenant_id: uuid.UUID,
        export_job_id: uuid.UUID,
        now: datetime,
        default_sign: bool,
        default_signature_key_id: str | None,
    ) -> ExportJobService:
        svc = ExportJobService(
            table="ops_reporting_export_job",
            rsg=Mock(),
            registry_provider=lambda: None,
        )
        svc._now_utc = Mock(return_value=now)
        svc._rsg.delete_many = AsyncMock()

        current = ExportJobDE(
            id=export_job_id,
            tenant_id=tenant_id,
            row_version=2,
            status="queued",
            export_type="report_snapshot_pack",
            spec_json={
                "ResourceRefs": {
                    "OpsWorkflowTasks": [str(uuid.uuid4())],
                }
            },
            default_sign=default_sign,
            default_signature_key_id=default_signature_key_id,
        )
        running = ExportJobDE(
            id=export_job_id,
            tenant_id=tenant_id,
            row_version=3,
            status="running",
            export_type="report_snapshot_pack",
            spec_json=current.spec_json,
            created_at=now,
            default_sign=default_sign,
            default_signature_key_id=default_signature_key_id,
        )

        svc._get_for_action = AsyncMock(return_value=current)
        svc._update_with_row_version = AsyncMock(return_value=running)
        svc._fetch_resource_payload = AsyncMock(
            return_value={
                "id": "task-1",
                "tenant_id": str(tenant_id),
                "row_version": 9,
            }
        )
        svc._build_snapshot_proof = AsyncMock(return_value=None)
        svc._build_audit_chain_proof = AsyncMock(return_value=None)
        svc._export_item_service.create = AsyncMock()
        svc.update = AsyncMock(
            return_value=ExportJobDE(
                id=export_job_id,
                tenant_id=tenant_id,
                row_version=4,
                status="completed",
            )
        )

        return svc

    async def test_action_create_export_queued(self) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        export_job_id = uuid.uuid4()

        svc = ExportJobService(
            table="ops_reporting_export_job",
            rsg=Mock(),
            registry_provider=lambda: None,
        )
        svc.create = AsyncMock(
            return_value=ExportJobDE(
                id=export_job_id,
                tenant_id=tenant_id,
                row_version=3,
                status="queued",
            )
        )

        result, status = await svc.action_create_export(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=actor_id,
            data=ExportJobCreateValidation(
                trace_id="trace-1",
                export_type="report_snapshot_pack",
                spec_json={
                    "ResourceRefs": {
                        "OpsReportingReportSnapshots": [str(uuid.uuid4())],
                    },
                    "ExportRef": "bundle://external/ref",
                },
            ),
        )

        self.assertEqual(status, 201)
        self.assertEqual(result["ExportJobId"], str(export_job_id))
        self.assertEqual(result["Status"], "queued")
        self.assertEqual(result["TraceId"], "trace-1")
        self.assertTrue(result["DefaultSign"])
        self.assertIsNone(result["DefaultSignatureKeyId"])

        create_payload = svc.create.await_args.args[0]
        self.assertTrue(create_payload["default_sign"])
        self.assertIsNone(create_payload["default_signature_key_id"])

    async def test_action_create_export_policy_deny_blocks(self) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        policy_definition_id = uuid.uuid4()

        svc = ExportJobService(
            table="ops_reporting_export_job",
            rsg=Mock(),
            registry_provider=lambda: None,
        )
        svc._policy_definition_service.get = AsyncMock(
            return_value=SimpleNamespace(
                row_version=2,
                is_active=True,
            )
        )
        svc._policy_definition_service.action_evaluate_policy = AsyncMock(
            return_value=({"Decision": "deny"}, 200)
        )

        with patch.object(export_job_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_create_export(
                    tenant_id=tenant_id,
                    where={"tenant_id": tenant_id},
                    auth_user_id=actor_id,
                    data=ExportJobCreateValidation(
                        export_type="report_snapshot_pack",
                        policy_definition_id=policy_definition_id,
                        spec_json={
                            "ResourceRefs": {
                                "OpsReportingReportSnapshots": [str(uuid.uuid4())],
                            }
                        },
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

    async def test_build_audit_chain_proof_calls_action_verify_chain(self) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = ExportJobService(
            table="ops_reporting_export_job",
            rsg=Mock(),
            registry_provider=lambda: None,
        )
        svc._audit_event_service.action_verify_chain = AsyncMock(
            return_value=({"IsValid": True, "CheckedRows": 3}, 200)
        )

        proof = await svc._build_audit_chain_proof(
            tenant_id=tenant_id,
            auth_user_id=actor_id,
            proofs_json={"AuditChain": {"RequireClean": False, "MaxRows": 10}},
        )

        self.assertEqual(proof["IsValid"], True)
        kwargs = svc._audit_event_service.action_verify_chain.await_args.kwargs
        self.assertEqual(kwargs["tenant_id"], tenant_id)
        self.assertEqual(kwargs["where"], {"tenant_id": tenant_id})
        self.assertEqual(kwargs["auth_user_id"], actor_id)
        self.assertIsNotNone(kwargs["data"])

    async def test_action_build_export_completed_and_idempotent(self) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        export_job_id = uuid.uuid4()
        now = datetime(2026, 2, 14, 20, 0, tzinfo=timezone.utc)

        svc = ExportJobService(
            table="ops_reporting_export_job",
            rsg=Mock(),
            registry_provider=lambda: None,
        )
        svc._now_utc = Mock(return_value=now)
        svc._rsg.delete_many = AsyncMock()

        current = ExportJobDE(
            id=export_job_id,
            tenant_id=tenant_id,
            row_version=2,
            status="queued",
            export_type="report_snapshot_pack",
            spec_json={
                "ResourceRefs": {
                    "OpsWorkflowTasks": [str(uuid.uuid4())],
                    "OpsReportingReportSnapshots": [str(uuid.uuid4())],
                }
            },
        )
        running = ExportJobDE(
            id=export_job_id,
            tenant_id=tenant_id,
            row_version=3,
            status="running",
            export_type="report_snapshot_pack",
            spec_json=current.spec_json,
            created_at=now,
        )

        svc._get_for_action = AsyncMock(return_value=current)
        svc._update_with_row_version = AsyncMock(return_value=running)
        svc._fetch_resource_payload = AsyncMock(
            side_effect=[
                {"id": "snap", "tenant_id": str(tenant_id), "row_version": 7},
                {"id": "task", "tenant_id": str(tenant_id), "row_version": 8},
            ]
        )
        svc._build_snapshot_proof = AsyncMock(return_value={"Checked": 1})
        svc._build_audit_chain_proof = AsyncMock(return_value=None)
        svc._resolve_signing_material = AsyncMock(
            return_value=SimpleNamespace(
                key_id="ops-key-1",
                secret=b"secret",
                provider="local",
            )
        )
        svc._export_item_service.create = AsyncMock()
        svc.update = AsyncMock(
            return_value=ExportJobDE(
                id=export_job_id,
                tenant_id=tenant_id,
                row_version=4,
                status="completed",
            )
        )

        result, status = await svc.action_build_export(
            tenant_id=tenant_id,
            entity_id=export_job_id,
            where={"tenant_id": tenant_id, "id": export_job_id},
            auth_user_id=actor_id,
            data=ExportJobBuildValidation(
                row_version=2,
                sign=True,
                signature_key_id="ops-key-1",
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["Status"], "completed")
        self.assertEqual(result["ItemCount"], 2)
        self.assertTrue(result["Signed"])

        first_create = svc._export_item_service.create.await_args_list[0].args[0]
        second_create = svc._export_item_service.create.await_args_list[1].args[0]
        self.assertLess(first_create["resource_type"], second_create["resource_type"])

        completed_current = ExportJobDE(
            id=export_job_id,
            tenant_id=tenant_id,
            row_version=4,
            status="completed",
            manifest_hash=result["ManifestHash"],
        )
        svc._get_for_action = AsyncMock(return_value=completed_current)
        svc._export_item_service.count = AsyncMock(return_value=2)

        idempotent_result, status = await svc.action_build_export(
            tenant_id=tenant_id,
            entity_id=export_job_id,
            where={"tenant_id": tenant_id, "id": export_job_id},
            auth_user_id=actor_id,
            data=ExportJobBuildValidation(
                row_version=4,
                force=False,
            ),
        )
        self.assertEqual(status, 200)
        self.assertTrue(idempotent_result["Idempotent"])

    async def test_action_build_export_uses_job_sign_false_default_when_omitted(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        export_job_id = uuid.uuid4()
        now = datetime(2026, 2, 14, 20, 0, tzinfo=timezone.utc)

        svc = self._build_ready_service(
            tenant_id=tenant_id,
            export_job_id=export_job_id,
            now=now,
            default_sign=False,
            default_signature_key_id="ops-key-default",
        )
        svc._resolve_signing_material = AsyncMock(
            return_value=SimpleNamespace(
                key_id="ops-key-default",
                secret=b"secret",
                provider="local",
            )
        )

        result, status = await svc.action_build_export(
            tenant_id=tenant_id,
            entity_id=export_job_id,
            where={"tenant_id": tenant_id, "id": export_job_id},
            auth_user_id=actor_id,
            data=ExportJobBuildValidation(row_version=2),
        )

        self.assertEqual(status, 200)
        self.assertFalse(result["Signed"])
        svc._resolve_signing_material.assert_not_awaited()

        changes = svc.update.await_args.kwargs["changes"]
        self.assertIsNone(changes["signature_json"])

    async def test_action_build_export_uses_job_signing_defaults_when_omitted(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        export_job_id = uuid.uuid4()
        now = datetime(2026, 2, 14, 20, 0, tzinfo=timezone.utc)

        svc = self._build_ready_service(
            tenant_id=tenant_id,
            export_job_id=export_job_id,
            now=now,
            default_sign=True,
            default_signature_key_id="ops-key-default",
        )
        svc._resolve_signing_material = AsyncMock(
            return_value=SimpleNamespace(
                key_id="ops-key-default",
                secret=b"secret",
                provider="local",
            )
        )

        result, status = await svc.action_build_export(
            tenant_id=tenant_id,
            entity_id=export_job_id,
            where={"tenant_id": tenant_id, "id": export_job_id},
            auth_user_id=actor_id,
            data=ExportJobBuildValidation(row_version=2),
        )

        self.assertEqual(status, 200)
        self.assertTrue(result["Signed"])
        svc._resolve_signing_material.assert_awaited_once_with(
            tenant_id=tenant_id,
            signature_key_id="ops-key-default",
        )

        changes = svc.update.await_args.kwargs["changes"]
        self.assertEqual(changes["signature_json"]["key_id"], "ops-key-default")

    async def test_action_build_export_explicit_sign_false_overrides_job_default(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        export_job_id = uuid.uuid4()
        now = datetime(2026, 2, 14, 20, 0, tzinfo=timezone.utc)

        svc = self._build_ready_service(
            tenant_id=tenant_id,
            export_job_id=export_job_id,
            now=now,
            default_sign=True,
            default_signature_key_id="ops-key-default",
        )
        svc._resolve_signing_material = AsyncMock(
            return_value=SimpleNamespace(
                key_id="ops-key-default",
                secret=b"secret",
                provider="local",
            )
        )

        result, status = await svc.action_build_export(
            tenant_id=tenant_id,
            entity_id=export_job_id,
            where={"tenant_id": tenant_id, "id": export_job_id},
            auth_user_id=actor_id,
            data=ExportJobBuildValidation(row_version=2, sign=False),
        )

        self.assertEqual(status, 200)
        self.assertFalse(result["Signed"])
        svc._resolve_signing_material.assert_not_awaited()

    async def test_action_verify_export_tamper_and_require_clean(self) -> None:
        tenant_id = uuid.uuid4()
        export_job_id = uuid.uuid4()

        svc = ExportJobService(
            table="ops_reporting_export_job",
            rsg=Mock(),
            registry_provider=lambda: None,
        )

        item = ExportItemDE(
            item_index=0,
            resource_type="OpsReportingReportSnapshots",
            resource_id=uuid.uuid4(),
            content_json={
                "EntitySet": "OpsReportingReportSnapshots",
                "Record": {"x": 1},
            },
        )
        item.content_hash = svc._sha256_hex(item.content_json)

        current = ExportJobDE(
            id=export_job_id,
            tenant_id=tenant_id,
            status="completed",
            export_type="report_snapshot_pack",
            spec_json={
                "ResourceRefs": {
                    "OpsReportingReportSnapshots": [str(item.resource_id)],
                }
            },
        )
        manifest = svc._build_manifest(
            job=current,
            spec_json=svc._canonical_spec_json(current.spec_json),
            items=[
                {
                    "item_index": 0,
                    "resource_type": item.resource_type,
                    "resource_id": str(item.resource_id),
                    "content_hash": item.content_hash,
                }
            ],
            proofs={},
            completed_at=None,
        )
        current.manifest_hash = svc._sha256_hex(manifest)
        current.signature_json = {
            "hash_alg": "hmac-sha256",
            "key_id": "ops-key-1",
            "signature": svc._hmac_sha256_hex(
                secret=b"secret",
                payload=current.manifest_hash,
            ),
        }

        svc.get = AsyncMock(return_value=current)
        svc._export_item_service.list = AsyncMock(return_value=[item])
        svc._key_ref_service.resolve_secret_for_key_id = AsyncMock(
            return_value=SimpleNamespace(
                key_id="ops-key-1",
                secret=b"secret",
                provider="local",
            )
        )

        valid_result, status = await svc.action_verify_export(
            tenant_id=tenant_id,
            entity_id=export_job_id,
            where={"tenant_id": tenant_id, "id": export_job_id},
            auth_user_id=uuid.uuid4(),
            data=ExportJobVerifyValidation(require_clean=False),
        )
        self.assertEqual(status, 200)
        self.assertTrue(valid_result["IsValid"])

        tampered_item = ExportItemDE(
            item_index=0,
            resource_type=item.resource_type,
            resource_id=item.resource_id,
            content_json={
                "EntitySet": "OpsReportingReportSnapshots",
                "Record": {"x": 99},
            },
            content_hash=item.content_hash,
        )
        svc._export_item_service.list = AsyncMock(return_value=[tampered_item])

        invalid_result, status = await svc.action_verify_export(
            tenant_id=tenant_id,
            entity_id=export_job_id,
            where={"tenant_id": tenant_id, "id": export_job_id},
            auth_user_id=uuid.uuid4(),
            data=ExportJobVerifyValidation(require_clean=False),
        )
        self.assertEqual(status, 200)
        self.assertFalse(invalid_result["IsValid"])

        with patch.object(export_job_mod, "abort", side_effect=_abort_raiser):
            svc._export_item_service.list = AsyncMock(return_value=[tampered_item])
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_verify_export(
                    tenant_id=tenant_id,
                    entity_id=export_job_id,
                    where={"tenant_id": tenant_id, "id": export_job_id},
                    auth_user_id=uuid.uuid4(),
                    data=ExportJobVerifyValidation(require_clean=True),
                )
            self.assertEqual(ex.exception.code, 409)
