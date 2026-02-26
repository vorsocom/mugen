"""Provides a CRUD service for export jobs and integrity actions."""

__all__ = ["ExportJobService"]

from datetime import datetime, timezone
import hashlib
import hmac
import json
import uuid
from typing import Any, Mapping

from pydantic import ValidationError
from quart import abort
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderBy,
    RowVersionConflict,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service.key_provider import ResolvedKeyMaterial
from mugen.core.plugin.acp.contract.service.key_ref import IKeyRefService
from mugen.core.plugin.acp.service.key_ref import KeyRefService
from mugen.core.plugin.audit.api.validation import AuditEventVerifyChainValidation
from mugen.core.plugin.audit.service.audit_event import AuditEventService
from mugen.core.plugin.ops_governance.api.validation import (
    EvaluatePolicyActionValidation,
)
from mugen.core.plugin.ops_governance.service.policy_definition import (
    PolicyDefinitionService,
)
from mugen.core.plugin.ops_reporting.api.validation import (
    ExportJobBuildValidation,
    ExportJobCreateValidation,
    ExportJobVerifyValidation,
    ReportSnapshotVerifyValidation,
)
from mugen.core.plugin.ops_reporting.contract.service.export_job import (
    IExportJobService,
)
from mugen.core.plugin.ops_reporting.domain import ExportJobDE
from mugen.core.plugin.ops_reporting.service.export_item import ExportItemService
from mugen.core.plugin.ops_reporting.service.report_snapshot import (
    ReportSnapshotService,
)


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


class ExportJobService(  # pragma: no cover
    IRelationalService[ExportJobDE],
    IExportJobService,
):
    """A CRUD service for deterministic export queue/build/verify actions."""

    _KEY_REF_TABLE = "admin_key_ref"
    _EXPORT_ITEM_TABLE = "ops_reporting_export_item"
    _REPORT_SNAPSHOT_TABLE = "ops_reporting_report_snapshot"
    _AUDIT_EVENT_TABLE = "audit_event"
    _POLICY_DEFINITION_TABLE = "ops_governance_policy_definition"

    _SIGNING_PURPOSE = "ops_reporting_signing"
    _MAX_ERROR_MESSAGE_LEN = 1024

    _RESOURCE_SET_ALIASES = {
        "OpsCaseCases": "OpsCases",
    }

    _ALLOWED_RESOURCE_SETS = {
        "OpsReportingReportSnapshots",
        "OpsCases",
        "OpsWorkflowInstances",
        "OpsWorkflowTasks",
        "OpsWorkflowDecisionRequests",
        "OpsWorkflowDecisionOutcomes",
        "OpsSlaClocks",
        "OpsSlaClockEvents",
        "OpsSlaEscalationRuns",
        "OpsDataHandlingRecords",
        "EvidenceBlobs",
        "AuditEvents",
    }

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        registry_provider=_registry_provider,
        **kwargs,
    ):
        super().__init__(
            de_type=ExportJobDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._registry_provider = registry_provider
        self._key_ref_service: IKeyRefService = KeyRefService(
            table=self._KEY_REF_TABLE,
            rsg=rsg,
        )
        self._export_item_service = ExportItemService(
            table=self._EXPORT_ITEM_TABLE,
            rsg=rsg,
        )
        self._snapshot_service = ReportSnapshotService(
            table=self._REPORT_SNAPSHOT_TABLE,
            rsg=rsg,
        )
        self._audit_event_service = AuditEventService(
            table=self._AUDIT_EVENT_TABLE,
            rsg=rsg,
        )
        self._policy_definition_service = PolicyDefinitionService(
            table=self._POLICY_DEFINITION_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: Any) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, uuid.UUID):
            return str(value)

        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()

        if isinstance(value, Mapping):
            return {str(k): cls._json_safe(v) for k, v in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(v) for v in value]

        if hasattr(value, "__dict__"):
            return {
                str(k): cls._json_safe(v)
                for k, v in vars(value).items()
                if not str(k).startswith("_")
            }

        return str(value)

    @classmethod
    def _canonical_json_bytes(cls, value: Any) -> bytes:
        return json.dumps(
            cls._json_safe(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def _sha256_hex(cls, value: Any) -> str:
        return hashlib.sha256(
            cls._canonical_json_bytes(value)
        ).hexdigest()  # noqa: S324

    @classmethod
    def _hmac_sha256_hex(cls, *, secret: bytes, payload: str) -> str:
        return hmac.new(
            secret,
            payload.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

    @classmethod
    def _canonical_resource_set(cls, entity_set: str) -> str:
        normalized = str(entity_set or "").strip()
        if normalized == "":
            abort(409, "SpecJson.ResourceRefs contains an empty entity set key.")
        return cls._RESOURCE_SET_ALIASES.get(normalized, normalized)

    @classmethod
    def _canonical_spec_json(cls, spec_json: Any) -> dict[str, Any]:
        if not isinstance(spec_json, Mapping):
            abort(409, "SpecJson must be a JSON object.")

        resource_refs_raw = spec_json.get("ResourceRefs")
        if not isinstance(resource_refs_raw, Mapping) or len(resource_refs_raw) == 0:
            abort(409, "SpecJson.ResourceRefs must be a non-empty object.")

        canonical_refs: dict[str, list[str]] = {}
        for raw_entity_set, raw_ids in resource_refs_raw.items():
            entity_set = cls._canonical_resource_set(str(raw_entity_set))
            if entity_set not in cls._ALLOWED_RESOURCE_SETS:
                abort(
                    409,
                    f"ResourceRefs includes unsupported EntitySet: {entity_set}.",
                )

            if not isinstance(raw_ids, list):
                abort(
                    409,
                    f"ResourceRefs[{entity_set}] must be an array of UUID values.",
                )

            parsed_ids: set[str] = set()
            for raw_id in raw_ids:
                try:
                    parsed_ids.add(str(uuid.UUID(str(raw_id))))
                except (TypeError, ValueError):
                    abort(
                        409,
                        (
                            "ResourceRefs contains a non-UUID value for "
                            f"{entity_set}."
                        ),
                    )

            canonical_refs[entity_set] = sorted(parsed_ids)

        proofs = spec_json.get("Proofs")
        if proofs is not None and not isinstance(proofs, Mapping):
            abort(409, "SpecJson.Proofs must be a JSON object if provided.")

        export_ref = cls._normalize_optional_text(spec_json.get("ExportRef"))

        canonical: dict[str, Any] = {
            "ResourceRefs": {
                entity_set: canonical_refs[entity_set]
                for entity_set in sorted(canonical_refs)
            }
        }
        if proofs is not None:
            canonical["Proofs"] = cls._json_safe(dict(proofs))
        if export_ref is not None:
            canonical["ExportRef"] = export_ref

        return canonical

    @classmethod
    def _build_manifest(
        cls,
        *,
        job: ExportJobDE,
        spec_json: dict[str, Any],
        items: list[dict[str, Any]],
        proofs: dict[str, Any] | None,
        completed_at: datetime | None,
    ) -> dict[str, Any]:
        return {
            "version": 1,
            "export_job": {
                "id": str(job.id) if job.id is not None else None,
                "tenant_id": str(job.tenant_id) if job.tenant_id is not None else None,
                "trace_id": cls._normalize_optional_text(job.trace_id),
                "export_type": cls._normalize_optional_text(job.export_type),
                "created_at": (
                    job.created_at.astimezone(timezone.utc).isoformat()
                    if job.created_at is not None
                    else None
                ),
                "completed_at": (
                    completed_at.astimezone(timezone.utc).isoformat()
                    if completed_at is not None
                    else None
                ),
                "created_by_user_id": (
                    str(job.created_by_user_id)
                    if job.created_by_user_id is not None
                    else None
                ),
            },
            "spec_json": spec_json,
            "items": [
                {
                    "item_index": int(item["item_index"]),
                    "resource_type": str(item["resource_type"]),
                    "resource_id": str(item["resource_id"]),
                    "content_hash": str(item["content_hash"]),
                }
                for item in items
            ],
            "proofs": proofs or {},
        }

    def _safe_registry(self) -> IAdminRegistry | None:
        try:
            return self._registry_provider()
        except Exception:  # pylint: disable=broad-except
            return None

    def _resolve_resource_service(self, entity_set: str):
        registry = self._safe_registry()
        if registry is None:
            abort(500, "Admin registry is unavailable.")

        try:
            resource = registry.get_resource(entity_set)
            return registry.get_edm_service(resource.service_key)
        except Exception:  # pylint: disable=broad-except
            abort(409, f"Resource service is not available for {entity_set}.")

    async def _resolve_signing_material(
        self,
        *,
        tenant_id: uuid.UUID,
        signature_key_id: str | None,
    ) -> ResolvedKeyMaterial:
        resolved: ResolvedKeyMaterial | None

        try:
            key_id = self._normalize_optional_text(signature_key_id)
            if key_id is not None:
                resolved = await self._key_ref_service.resolve_secret_for_key_id(
                    tenant_id=tenant_id,
                    purpose=self._SIGNING_PURPOSE,
                    key_id=key_id,
                )
            else:
                resolved = await self._key_ref_service.resolve_secret_for_purpose(
                    tenant_id=tenant_id,
                    purpose=self._SIGNING_PURPOSE,
                )
        except SQLAlchemyError:
            abort(500)

        if resolved is None:
            abort(
                409,
                (
                    "Signing key was requested but no active key material "
                    "resolved for purpose ops_reporting_signing."
                ),
            )

        return resolved

    def _build_signature_json(
        self,
        *,
        manifest_hash: str,
        material: ResolvedKeyMaterial,
        signed_at: datetime,
    ) -> dict[str, Any]:
        return {
            "hash_alg": "hmac-sha256",
            "key_id": material.key_id,
            "provider": material.provider,
            "signed_at": signed_at.isoformat(),
            "signature": self._hmac_sha256_hex(
                secret=material.secret,
                payload=manifest_hash,
            ),
        }

    async def _verify_signature(
        self,
        *,
        tenant_id: uuid.UUID,
        signature_json: Mapping[str, Any],
        manifest_hash: str,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        hash_alg = str(signature_json.get("hash_alg") or "hmac-sha256").strip().lower()
        if hash_alg != "hmac-sha256":
            reasons.append("unsupported_signature_algorithm")
            return False, reasons

        key_id = self._normalize_optional_text(signature_json.get("key_id"))
        if key_id is None:
            reasons.append("signature_missing_key_id")
            return False, reasons

        signature = self._normalize_optional_text(signature_json.get("signature"))
        if signature is None:
            reasons.append("signature_missing_value")
            return False, reasons

        try:
            resolved = await self._key_ref_service.resolve_secret_for_key_id(
                tenant_id=tenant_id,
                purpose=self._SIGNING_PURPOSE,
                key_id=key_id,
            )
        except SQLAlchemyError:
            abort(500)

        if resolved is None:
            reasons.append("signature_key_unresolved")
            return False, reasons

        expected_signature = self._hmac_sha256_hex(
            secret=resolved.secret,
            payload=manifest_hash,
        )
        if not hmac.compare_digest(signature.lower(), expected_signature):
            reasons.append("signature_mismatch")
            return False, reasons

        return True, reasons

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> ExportJobDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version

        try:
            current = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            return current

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, "Export job not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> ExportJobDE:
        svc: ICrudServiceWithRowVersion[ExportJobDE] = self

        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return updated

    async def _mark_failed(
        self,
        *,
        tenant_id: uuid.UUID,
        export_job_id: uuid.UUID,
        error_message: str,
    ) -> None:
        message = self._normalize_optional_text(error_message) or "export_build_failed"
        if len(message) > self._MAX_ERROR_MESSAGE_LEN:
            message = message[: self._MAX_ERROR_MESSAGE_LEN]

        try:
            await self.update(
                where={
                    "tenant_id": tenant_id,
                    "id": export_job_id,
                },
                changes={
                    "status": "failed",
                    "manifest_json": None,
                    "manifest_hash": None,
                    "signature_json": None,
                    "completed_at": None,
                    "error_message": message,
                },
            )
        except SQLAlchemyError:
            pass

    async def _evaluate_policy_gate(
        self,
        *,
        tenant_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        policy_definition_id: uuid.UUID,
        trace_id: str | None,
        export_type: str,
        spec_json: dict[str, Any],
    ) -> dict[str, Any]:
        policy = await self._policy_definition_service.get(
            {
                "tenant_id": tenant_id,
                "id": policy_definition_id,
            }
        )
        if policy is None:
            abort(409, "PolicyDefinitionId did not resolve to an active policy.")
        if not bool(policy.is_active):
            abort(409, "PolicyDefinitionId is inactive.")

        policy_row_version = int(policy.row_version or 0)
        if policy_row_version <= 0:
            abort(409, "PolicyDefinitionId has invalid RowVersion.")

        evaluate_result, _status = (
            await self._policy_definition_service.action_evaluate_policy(
                tenant_id=tenant_id,
                entity_id=policy_definition_id,
                where={"tenant_id": tenant_id, "id": policy_definition_id},
                auth_user_id=auth_user_id,
                data=EvaluatePolicyActionValidation(
                    row_version=policy_row_version,
                    trace_id=trace_id,
                    subject_namespace="ops.reporting.export_job",
                    subject_id=None,
                    subject_ref=trace_id or export_type,
                    input_json={
                        "ExportType": export_type,
                        "SpecJson": spec_json,
                    },
                    actor_json={"UserId": str(auth_user_id)},
                    request_context={
                        "PolicyDefinitionId": str(policy_definition_id),
                    },
                ),
            )
        )

        decision_snapshot = (
            dict(evaluate_result)
            if isinstance(evaluate_result, Mapping)
            else {"Decision": "deny"}
        )

        decision = str(decision_snapshot.get("Decision") or "").strip().lower()
        if decision in {"deny", "review"}:
            abort(
                409,
                f"Export policy gate blocked create_export with decision={decision}.",
            )

        return decision_snapshot

    async def _fetch_resource_payload(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_set: str,
        resource_id: uuid.UUID,
    ) -> dict[str, Any]:
        service = self._resolve_resource_service(entity_set)

        row = None
        try:
            row = await service.get({"tenant_id": tenant_id, "id": resource_id})
        except SQLAlchemyError:
            abort(500)
        except Exception:  # pylint: disable=broad-except
            row = None

        if row is None:
            try:
                row = await service.get({"id": resource_id})
            except SQLAlchemyError:
                abort(500)
            except Exception:  # pylint: disable=broad-except
                row = None

        if row is None:
            abort(
                409,
                (
                    "Export build failed because "
                    f"{entity_set}/{resource_id} was not found."
                ),
            )

        row_tenant_id = getattr(row, "tenant_id", None)
        if row_tenant_id is not None and row_tenant_id != tenant_id:
            abort(
                409,
                (
                    "Export build blocked cross-tenant reference for "
                    f"{entity_set}/{resource_id}."
                ),
            )

        return self._json_safe(vars(row))

    async def _build_snapshot_proof(
        self,
        *,
        tenant_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        resource_refs: Mapping[str, list[str]],
    ) -> dict[str, Any] | None:
        snapshot_ids = resource_refs.get("OpsReportingReportSnapshots") or []
        if not snapshot_ids:
            return None

        results: list[dict[str, Any]] = []
        invalid_count = 0
        for snapshot_id_text in snapshot_ids:
            snapshot_id = uuid.UUID(snapshot_id_text)
            verify_result, _status = (
                await self._snapshot_service.action_verify_snapshot(
                    tenant_id=tenant_id,
                    entity_id=snapshot_id,
                    where={
                        "tenant_id": tenant_id,
                        "id": snapshot_id,
                    },
                    auth_user_id=auth_user_id,
                    data=ReportSnapshotVerifyValidation(require_clean=False),
                )
            )
            if not bool(verify_result.get("IsValid")):
                invalid_count += 1

            results.append(
                {
                    "SnapshotId": snapshot_id_text,
                    **self._json_safe(verify_result),
                }
            )

        return {
            "Checked": len(results),
            "InvalidCount": invalid_count,
            "Results": results,
        }

    async def _build_audit_chain_proof(
        self,
        *,
        tenant_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        proofs_json: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(proofs_json, Mapping):
            return None

        audit_chain_payload = proofs_json.get("AuditChain")
        if audit_chain_payload is None:
            return None

        if not isinstance(audit_chain_payload, Mapping):
            abort(409, "SpecJson.Proofs.AuditChain must be a JSON object.")

        try:
            validation = AuditEventVerifyChainValidation.model_validate(
                dict(audit_chain_payload)
            )
        except ValidationError as error:
            abort(409, str(error))

        summary, _status = await self._audit_event_service.action_verify_chain(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=auth_user_id,
            data=validation,
        )
        return self._json_safe(summary)

    async def action_create_export(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ExportJobCreateValidation,
    ) -> tuple[dict[str, Any], int]:
        """Create a queued export job, with optional policy gate enforcement."""
        _ = where

        trace_id = self._normalize_optional_text(data.trace_id)
        export_type = str(data.export_type).strip().lower()
        spec_json = self._canonical_spec_json(data.spec_json)

        policy_decision_json: dict[str, Any] | None = None
        if data.policy_definition_id is not None:
            policy_decision_json = await self._evaluate_policy_gate(
                tenant_id=tenant_id,
                auth_user_id=auth_user_id,
                policy_definition_id=data.policy_definition_id,
                trace_id=trace_id,
                export_type=export_type,
                spec_json=spec_json,
            )

        try:
            created = await self.create(
                {
                    "tenant_id": tenant_id,
                    "trace_id": trace_id,
                    "export_type": export_type,
                    "spec_json": spec_json,
                    "status": "queued",
                    "export_ref": self._normalize_optional_text(
                        spec_json.get("ExportRef")
                    ),
                    "policy_decision_json": policy_decision_json,
                    "created_by_user_id": auth_user_id,
                    "attributes": (
                        dict(data.attributes) if data.attributes is not None else None
                    ),
                }
            )
        except SQLAlchemyError:
            abort(500)

        if created.id is None:
            abort(500, "Export job ID was not generated.")

        return (
            {
                "ExportJobId": str(created.id),
                "Status": str(created.status),
                "RowVersion": int(created.row_version or 0),
                "TraceId": trace_id,
            },
            201,
        )

    async def action_build_export(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ExportJobBuildValidation,
    ) -> tuple[dict[str, Any], int]:
        """Build deterministic export items, proofs, manifest hash, and signature."""
        expected_row_version = int(data.row_version)

        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.id is None:
            abort(409, "Export job identifier is missing.")

        if current.status == "completed" and not bool(data.force):
            item_count = await self._export_item_service.count(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "export_job_id": current.id,
                        }
                    )
                ]
            )
            return (
                {
                    "ExportJobId": str(current.id),
                    "Status": "completed",
                    "ManifestHash": self._normalize_optional_text(
                        current.manifest_hash
                    ),
                    "ItemCount": int(item_count),
                    "RowVersion": int(current.row_version or 0),
                    "Idempotent": True,
                },
                200,
            )

        if current.status == "running" and not bool(data.force):
            abort(409, "Export job is already running.")

        running = await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "running",
                "error_message": None,
            },
        )

        if running.id is None:
            abort(409, "Export job identifier is missing.")

        try:
            spec_json = self._canonical_spec_json(running.spec_json)

            await self._rsg.delete_many(
                self._EXPORT_ITEM_TABLE,
                where={
                    "tenant_id": tenant_id,
                    "export_job_id": running.id,
                },
            )

            resource_refs = spec_json["ResourceRefs"]
            item_rows: list[dict[str, Any]] = []
            next_index = 0
            for entity_set in sorted(resource_refs):
                for resource_id_text in resource_refs[entity_set]:
                    resource_id = uuid.UUID(resource_id_text)
                    payload = await self._fetch_resource_payload(
                        tenant_id=tenant_id,
                        entity_set=entity_set,
                        resource_id=resource_id,
                    )
                    content_json = {
                        "EntitySet": entity_set,
                        "EntityId": resource_id_text,
                        "Record": payload,
                    }
                    content_hash = self._sha256_hex(content_json)

                    await self._export_item_service.create(
                        {
                            "tenant_id": tenant_id,
                            "export_job_id": running.id,
                            "item_index": next_index,
                            "resource_type": entity_set,
                            "resource_id": resource_id,
                            "content_hash": content_hash,
                            "content_json": content_json,
                            "meta_json": {
                                "RecordRowVersion": payload.get("row_version"),
                            },
                        }
                    )

                    item_rows.append(
                        {
                            "item_index": next_index,
                            "resource_type": entity_set,
                            "resource_id": resource_id_text,
                            "content_hash": content_hash,
                        }
                    )
                    next_index += 1

            proofs: dict[str, Any] = {}
            snapshot_proof = await self._build_snapshot_proof(
                tenant_id=tenant_id,
                auth_user_id=auth_user_id,
                resource_refs=resource_refs,
            )
            if snapshot_proof is not None:
                proofs["SnapshotVerification"] = snapshot_proof

            audit_chain_proof = await self._build_audit_chain_proof(
                tenant_id=tenant_id,
                auth_user_id=auth_user_id,
                proofs_json=spec_json.get("Proofs"),
            )
            if audit_chain_proof is not None:
                proofs["AuditChain"] = audit_chain_proof

            completed_at = self._now_utc()
            manifest_json = self._build_manifest(
                job=running,
                spec_json=spec_json,
                items=item_rows,
                proofs=proofs,
                completed_at=completed_at,
            )
            manifest_hash = self._sha256_hex(manifest_json)

            signature_json: dict[str, Any] | None = None
            if bool(data.sign):
                material = await self._resolve_signing_material(
                    tenant_id=tenant_id,
                    signature_key_id=data.signature_key_id,
                )
                signature_json = self._build_signature_json(
                    manifest_hash=manifest_hash,
                    material=material,
                    signed_at=completed_at,
                )

            export_ref = self._normalize_optional_text(running.export_ref)
            if export_ref is None:
                export_ref = self._normalize_optional_text(spec_json.get("ExportRef"))

            updated = await self.update(
                where={
                    "tenant_id": tenant_id,
                    "id": running.id,
                },
                changes={
                    "status": "completed",
                    "manifest_json": manifest_json,
                    "manifest_hash": manifest_hash,
                    "signature_json": signature_json,
                    "export_ref": export_ref,
                    "completed_at": completed_at,
                    "error_message": None,
                },
            )
            if updated is None:
                abort(404, "Export job not found.")

            return (
                {
                    "ExportJobId": str(updated.id),
                    "Status": "completed",
                    "ManifestHash": manifest_hash,
                    "ItemCount": len(item_rows),
                    "RowVersion": int(updated.row_version or 0),
                    "Signed": signature_json is not None,
                },
                200,
            )
        except HTTPException as error:
            await self._mark_failed(
                tenant_id=tenant_id,
                export_job_id=running.id,
                error_message=str(error),
            )
            raise
        except SQLAlchemyError as error:
            await self._mark_failed(
                tenant_id=tenant_id,
                export_job_id=running.id,
                error_message=str(error),
            )
            abort(500)

    async def action_verify_export(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ExportJobVerifyValidation,
    ) -> tuple[dict[str, Any], int]:
        """Verify deterministic item hashes, manifest hash, and signature."""
        _ = entity_id
        _ = auth_user_id

        try:
            current = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if current is None:
            abort(404, "Export job not found.")

        if current.id is None:
            abort(409, "Export job identifier is missing.")

        items = await self._export_item_service.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "export_job_id": current.id,
                    }
                )
            ],
            order_by=[
                OrderBy(field="item_index"),
                OrderBy(field="id"),
            ],
        )

        checks: list[dict[str, Any]] = []
        reasons: list[str] = []

        manifest_items: list[dict[str, Any]] = []
        for item in items:
            computed_hash = self._sha256_hex(item.content_json or {})
            stored_hash = self._normalize_optional_text(item.content_hash)
            item_ok = stored_hash is not None and stored_hash.lower() == computed_hash

            checks.append(
                {
                    "Name": "item_hash_match",
                    "ItemIndex": int(item.item_index or 0),
                    "IsValid": item_ok,
                }
            )
            if not item_ok:
                reasons.append(f"item_hash_mismatch:{int(item.item_index or 0)}")

            manifest_items.append(
                {
                    "item_index": int(item.item_index or 0),
                    "resource_type": str(item.resource_type),
                    "resource_id": str(item.resource_id),
                    "content_hash": computed_hash,
                }
            )

        try:
            spec_json = self._canonical_spec_json(current.spec_json)
        except HTTPException:
            spec_json = {"ResourceRefs": {}}
            checks.append({"Name": "spec_json_valid", "IsValid": False})
            reasons.append("spec_json_invalid")
        else:
            checks.append({"Name": "spec_json_valid", "IsValid": True})

        proofs = {}
        if isinstance(current.manifest_json, Mapping):
            if isinstance(current.manifest_json.get("proofs"), Mapping):
                proofs = dict(current.manifest_json.get("proofs") or {})
            elif isinstance(current.manifest_json.get("Proofs"), Mapping):
                proofs = dict(current.manifest_json.get("Proofs") or {})

        manifest_json = self._build_manifest(
            job=current,
            spec_json=spec_json,
            items=manifest_items,
            proofs=proofs,
            completed_at=current.completed_at,
        )
        computed_manifest_hash = self._sha256_hex(manifest_json)

        stored_manifest_hash = self._normalize_optional_text(current.manifest_hash)
        checks.append(
            {
                "Name": "manifest_hash_present",
                "IsValid": stored_manifest_hash is not None,
            }
        )
        if stored_manifest_hash is None:
            reasons.append("manifest_hash_missing")
        else:
            manifest_ok = stored_manifest_hash.lower() == computed_manifest_hash.lower()
            checks.append({"Name": "manifest_hash_match", "IsValid": manifest_ok})
            if not manifest_ok:
                reasons.append("manifest_hash_mismatch")

        if current.signature_json is None:
            checks.append(
                {
                    "Name": "signature_present",
                    "IsValid": False,
                    "Skipped": True,
                }
            )
        elif not isinstance(current.signature_json, Mapping):
            checks.append({"Name": "signature_shape", "IsValid": False})
            reasons.append("signature_json_invalid")
        else:
            checks.append({"Name": "signature_present", "IsValid": True})
            signature_ok, signature_reasons = await self._verify_signature(
                tenant_id=tenant_id,
                signature_json=current.signature_json,
                manifest_hash=computed_manifest_hash,
            )
            checks.append({"Name": "signature_valid", "IsValid": signature_ok})
            reasons.extend(signature_reasons)

        is_valid = len(reasons) == 0
        result = {
            "IsValid": is_valid,
            "Checks": checks,
            "Reasons": list(dict.fromkeys(reasons)),
            "ManifestHash": computed_manifest_hash,
            "CheckedItems": len(manifest_items),
        }

        if bool(data.require_clean) and not is_valid:
            abort(409, "Export verification failed.")

        return result, 200
