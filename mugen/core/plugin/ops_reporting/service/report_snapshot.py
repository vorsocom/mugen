"""Provides a CRUD service for report snapshot lifecycle actions."""

__all__ = ["ReportSnapshotService"]

from datetime import datetime, timezone
import hashlib
import hmac
import json
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderBy,
    RowVersionConflict,
    ScalarFilter,
    ScalarFilterOp,
)
from mugen.core.plugin.acp.contract.service.key_provider import ResolvedKeyMaterial
from mugen.core.plugin.acp.contract.service.key_ref import IKeyRefService
from mugen.core.plugin.acp.service.key_ref import KeyRefService
from mugen.core.plugin.ops_reporting.api.validation import (
    ReportSnapshotArchiveValidation,
    ReportSnapshotGenerateValidation,
    ReportSnapshotPublishValidation,
    ReportSnapshotVerifyValidation,
)
from mugen.core.plugin.ops_reporting.contract.service.report_snapshot import (
    IReportSnapshotService,
)
from mugen.core.plugin.ops_reporting.domain import ReportSnapshotDE
from mugen.core.plugin.ops_reporting.service.metric_definition import (
    MetricDefinitionService,
)
from mugen.core.plugin.ops_reporting.service.metric_series import MetricSeriesService
from mugen.core.plugin.ops_reporting.service.report_definition import (
    ReportDefinitionService,
)


class ReportSnapshotService(
    IRelationalService[ReportSnapshotDE],
    IReportSnapshotService,
):
    """A CRUD service for report snapshot generation, publish, archive, and verify."""

    _METRIC_DEFINITION_TABLE = "ops_reporting_metric_definition"
    _METRIC_SERIES_TABLE = "ops_reporting_metric_series"
    _REPORT_DEFINITION_TABLE = "ops_reporting_report_definition"
    _KEY_REF_TABLE = "admin_key_ref"
    _SIGNING_PURPOSE = "ops_reporting_signing"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ReportSnapshotDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._metric_definition_service = MetricDefinitionService(
            table=self._METRIC_DEFINITION_TABLE,
            rsg=rsg,
        )
        self._metric_series_service = MetricSeriesService(
            table=self._METRIC_SERIES_TABLE,
            rsg=rsg,
        )
        self._report_definition_service = ReportDefinitionService(
            table=self._REPORT_DEFINITION_TABLE,
            rsg=rsg,
        )
        self._key_ref_service: IKeyRefService = KeyRefService(
            table=self._KEY_REF_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_scope_key(value: str | None) -> str:
        clean = str(value or "").strip()
        return clean or "__all__"

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _normalize_metric_codes(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []

        codes: list[str] = []
        for item in raw:
            clean = str(item or "").strip()
            if clean:
                codes.append(clean)

        return list(dict.fromkeys(codes))

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

    @staticmethod
    def _normalize_optional_json(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        return None

    def _build_snapshot_provenance(
        self,
        *,
        trace_id: str | None,
        window_start: datetime,
        window_end: datetime,
        scope_key: str,
        metric_definitions: list[dict[str, Any]],
        provenance_refs_json: Any,
    ) -> dict[str, Any]:
        provenance: dict[str, Any] = {
            "version": 1,
            "aggregation": {
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "scope_key": scope_key,
            },
            "metric_definitions": metric_definitions,
        }
        if trace_id is not None:
            provenance["trace_id"] = trace_id

        refs_json = self._normalize_optional_json(provenance_refs_json)
        if refs_json is not None:
            provenance["refs"] = refs_json

        return provenance

    def _build_snapshot_manifest(
        self,
        *,
        snapshot: ReportSnapshotDE,
        metric_codes: list[str],
        window_start: datetime,
        window_end: datetime,
        scope_key: str,
        summary: dict[str, Any],
        provenance: dict[str, Any],
        trace_id: str | None,
        generated_at: datetime,
        generated_by_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        return {
            "version": 1,
            "snapshot": {
                "id": str(snapshot.id) if snapshot.id is not None else None,
                "tenant_id": (
                    str(snapshot.tenant_id) if snapshot.tenant_id is not None else None
                ),
                "report_definition_id": (
                    str(snapshot.report_definition_id)
                    if snapshot.report_definition_id is not None
                    else None
                ),
                "metric_codes": list(metric_codes),
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "scope_key": scope_key,
                "trace_id": trace_id,
                "generated_at": generated_at.isoformat(),
                "generated_by_user_id": str(generated_by_user_id),
            },
            "summary": summary,
            "provenance": provenance,
        }

    def _build_manifest_from_snapshot(
        self, snapshot: ReportSnapshotDE
    ) -> dict[str, Any]:
        summary_json = (
            snapshot.summary_json if isinstance(snapshot.summary_json, dict) else {}
        )
        provenance_json = (
            snapshot.provenance_json
            if isinstance(snapshot.provenance_json, dict)
            else {}
        )

        return {
            "version": 1,
            "snapshot": {
                "id": str(snapshot.id) if snapshot.id is not None else None,
                "tenant_id": (
                    str(snapshot.tenant_id) if snapshot.tenant_id is not None else None
                ),
                "report_definition_id": (
                    str(snapshot.report_definition_id)
                    if snapshot.report_definition_id is not None
                    else None
                ),
                "metric_codes": self._normalize_metric_codes(snapshot.metric_codes),
                "window_start": (
                    self._to_aware_utc(snapshot.window_start).isoformat()
                    if snapshot.window_start is not None
                    else None
                ),
                "window_end": (
                    self._to_aware_utc(snapshot.window_end).isoformat()
                    if snapshot.window_end is not None
                    else None
                ),
                "scope_key": self._normalize_scope_key(snapshot.scope_key),
                "trace_id": self._normalize_optional_text(snapshot.trace_id),
                "generated_at": (
                    self._to_aware_utc(snapshot.generated_at).isoformat()
                    if snapshot.generated_at is not None
                    else None
                ),
                "generated_by_user_id": (
                    str(snapshot.generated_by_user_id)
                    if snapshot.generated_by_user_id is not None
                    else None
                ),
            },
            "summary": summary_json,
            "provenance": provenance_json,
        }

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

    async def create(self, values: Mapping[str, Any]) -> ReportSnapshotDE:
        create_values = dict(values)

        create_values["scope_key"] = self._normalize_scope_key(
            create_values.get("scope_key")
        )

        metric_codes = create_values.get("metric_codes")
        if metric_codes is not None:
            create_values["metric_codes"] = self._normalize_metric_codes(metric_codes)

        if not create_values.get("status"):
            create_values["status"] = "draft"

        create_values["note"] = self._normalize_optional_text(create_values.get("note"))
        create_values["trace_id"] = self._normalize_optional_text(
            create_values.get("trace_id")
        )

        return await super().create(create_values)

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> ReportSnapshotDE:
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
            abort(404, "Report snapshot not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_snapshot_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> ReportSnapshotDE:
        svc: ICrudServiceWithRowVersion[ReportSnapshotDE] = self

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

    async def _resolve_metric_codes(
        self,
        *,
        tenant_id: uuid.UUID,
        snapshot: ReportSnapshotDE,
    ) -> list[str]:
        codes = self._normalize_metric_codes(snapshot.metric_codes)
        if codes:
            return codes

        if snapshot.report_definition_id is None:
            abort(409, "Snapshot has no ReportDefinitionId or MetricCodes.")

        report_definition = await self._report_definition_service.get(
            {
                "tenant_id": tenant_id,
                "id": snapshot.report_definition_id,
            }
        )
        if report_definition is None:
            abort(409, "ReportDefinitionId does not resolve to an existing report.")

        report_codes = self._normalize_metric_codes(report_definition.metric_codes)
        if not report_codes:
            abort(409, "Resolved report definition has no MetricCodes.")

        return report_codes

    def _resolve_window(
        self,
        *,
        snapshot: ReportSnapshotDE,
        data: ReportSnapshotGenerateValidation,
    ) -> tuple[datetime, datetime]:
        window_start = data.window_start or snapshot.window_start
        window_end = data.window_end or snapshot.window_end

        if window_start is None or window_end is None:
            abort(
                409,
                "Provide WindowStart and WindowEnd on snapshot or action payload.",
            )

        window_start = self._to_aware_utc(window_start)
        window_end = self._to_aware_utc(window_end)

        if window_end <= window_start:
            abort(400, "WindowEnd must be > WindowStart.")

        return window_start, window_end

    async def _build_metric_summary_with_provenance(
        self,
        *,
        tenant_id: uuid.UUID,
        metric_codes: list[str],
        window_start: datetime,
        window_end: datetime,
        scope_key: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        metrics: list[dict[str, Any]] = []
        provenance_metrics: list[dict[str, Any]] = []

        for code in metric_codes:
            metric_definition = await self._metric_definition_service.get(
                {
                    "tenant_id": tenant_id,
                    "code": code,
                }
            )

            if metric_definition is None or metric_definition.id is None:
                metrics.append(
                    {
                        "metric_code": code,
                        "metric_name": None,
                        "missing_metric_definition": True,
                        "bucket_count": 0,
                        "source_count": 0,
                        "value_numeric": 0,
                    }
                )
                provenance_metrics.append(
                    {
                        "metric_code": code,
                        "metric_definition_id": None,
                        "metric_definition_row_version": None,
                        "missing_metric_definition": True,
                        "series_refs": [],
                    }
                )
                continue

            rows = await self._metric_series_service.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "metric_definition_id": metric_definition.id,
                            "scope_key": scope_key,
                        },
                        scalar_filters=(
                            ScalarFilter(
                                field="bucket_start",
                                op=ScalarFilterOp.GTE,
                                value=window_start,
                            ),
                            ScalarFilter(
                                field="bucket_end",
                                op=ScalarFilterOp.LTE,
                                value=window_end,
                            ),
                        ),
                    )
                ],
                order_by=[
                    OrderBy(field="bucket_start"),
                    OrderBy(field="bucket_end"),
                    OrderBy(field="id"),
                ],
            )

            value_numeric = sum(int(row.value_numeric or 0) for row in rows)
            source_count = sum(int(row.source_count or 0) for row in rows)

            last_computed = None
            series_refs: list[dict[str, Any]] = []
            for row in rows:
                if row.computed_at is not None and (
                    last_computed is None or row.computed_at > last_computed
                ):
                    last_computed = row.computed_at

                row_ref = {
                    "id": str(row.id) if row.id is not None else None,
                    "row_version": (
                        int(row.row_version) if row.row_version is not None else None
                    ),
                    "bucket_start": (
                        self._to_aware_utc(row.bucket_start).isoformat()
                        if row.bucket_start is not None
                        else None
                    ),
                    "bucket_end": (
                        self._to_aware_utc(row.bucket_end).isoformat()
                        if row.bucket_end is not None
                        else None
                    ),
                    "computed_at": (
                        self._to_aware_utc(row.computed_at).isoformat()
                        if row.computed_at is not None
                        else None
                    ),
                    "value_numeric": int(row.value_numeric or 0),
                    "source_count": int(row.source_count or 0),
                }
                row_ref["content_hash"] = self._sha256_hex(row_ref)
                series_refs.append(row_ref)

            metrics.append(
                {
                    "metric_code": code,
                    "metric_name": metric_definition.name,
                    "missing_metric_definition": False,
                    "bucket_count": len(rows),
                    "source_count": source_count,
                    "value_numeric": value_numeric,
                    "last_computed_at": (
                        self._to_aware_utc(last_computed).isoformat()
                        if last_computed is not None
                        else None
                    ),
                }
            )

            provenance_metrics.append(
                {
                    "metric_code": code,
                    "metric_definition_id": str(metric_definition.id),
                    "metric_definition_row_version": (
                        int(metric_definition.row_version)
                        if metric_definition.row_version is not None
                        else None
                    ),
                    "missing_metric_definition": False,
                    "series_refs": series_refs,
                }
            )

        return metrics, provenance_metrics

    async def _build_metric_summary(
        self,
        *,
        tenant_id: uuid.UUID,
        metric_codes: list[str],
        window_start: datetime,
        window_end: datetime,
        scope_key: str,
    ) -> list[dict[str, Any]]:
        metrics, _provenance = await self._build_metric_summary_with_provenance(
            tenant_id=tenant_id,
            metric_codes=metric_codes,
            window_start=window_start,
            window_end=window_end,
            scope_key=scope_key,
        )
        return metrics

    async def action_generate_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ReportSnapshotGenerateValidation,
    ) -> tuple[dict[str, Any], int]:
        """Generate snapshot summary payload from metric-series rows."""
        _ = entity_id

        expected_row_version = int(data.row_version)

        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "archived":
            abort(409, "Archived snapshots cannot be regenerated.")

        metric_codes = await self._resolve_metric_codes(
            tenant_id=tenant_id,
            snapshot=current,
        )
        window_start, window_end = self._resolve_window(snapshot=current, data=data)
        scope_key = self._normalize_scope_key(data.scope_key or current.scope_key)
        trace_id = (
            self._normalize_optional_text(data.trace_id)
            if data.trace_id is not None
            else self._normalize_optional_text(current.trace_id)
        )

        metrics, provenance_metrics = await self._build_metric_summary_with_provenance(
            tenant_id=tenant_id,
            metric_codes=metric_codes,
            window_start=window_start,
            window_end=window_end,
            scope_key=scope_key,
        )

        now = self._now_utc()
        summary = {
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "scope_key": scope_key,
            "metric_count": len(metrics),
            "metrics": metrics,
            "generated_at": now.isoformat(),
        }

        provenance = self._build_snapshot_provenance(
            trace_id=trace_id,
            window_start=window_start,
            window_end=window_end,
            scope_key=scope_key,
            metric_definitions=provenance_metrics,
            provenance_refs_json=data.provenance_refs_json,
        )

        manifest = self._build_snapshot_manifest(
            snapshot=current,
            metric_codes=metric_codes,
            window_start=window_start,
            window_end=window_end,
            scope_key=scope_key,
            summary=summary,
            provenance=provenance,
            trace_id=trace_id,
            generated_at=now,
            generated_by_user_id=auth_user_id,
        )
        manifest_hash = self._sha256_hex(manifest)

        signature_json: dict[str, Any] | None = None
        if bool(data.sign):
            material = await self._resolve_signing_material(
                tenant_id=tenant_id,
                signature_key_id=data.signature_key_id,
            )
            signature_json = self._build_signature_json(
                manifest_hash=manifest_hash,
                material=material,
                signed_at=now,
            )

        await self._update_snapshot_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "generated",
                "window_start": window_start,
                "window_end": window_end,
                "scope_key": scope_key,
                "metric_codes": metric_codes,
                "summary_json": summary,
                "trace_id": trace_id,
                "provenance_json": provenance,
                "manifest_hash": manifest_hash,
                "signature_json": signature_json,
                "generated_at": now,
                "generated_by_user_id": auth_user_id,
                "note": self._normalize_optional_text(data.note),
            },
        )

        return "", 204

    async def action_publish_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ReportSnapshotPublishValidation,
    ) -> tuple[dict[str, Any], int]:
        """Publish a generated report snapshot."""
        _ = tenant_id
        _ = entity_id

        expected_row_version = int(data.row_version)

        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "archived":
            abort(409, "Archived snapshots cannot be published.")

        if current.status == "published":
            return "", 204

        if current.status != "generated":
            abort(409, "Snapshot must be generated before publish.")

        now = self._now_utc()

        await self._update_snapshot_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "published",
                "published_at": now,
                "published_by_user_id": auth_user_id,
                "note": self._normalize_optional_text(data.note),
            },
        )

        return "", 204

    async def action_archive_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ReportSnapshotArchiveValidation,
    ) -> tuple[dict[str, Any], int]:
        """Archive a report snapshot."""
        _ = tenant_id
        _ = entity_id

        expected_row_version = int(data.row_version)

        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "archived":
            return "", 204

        now = self._now_utc()

        await self._update_snapshot_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "archived",
                "archived_at": now,
                "archived_by_user_id": auth_user_id,
                "note": self._normalize_optional_text(data.note),
            },
        )

        return "", 204

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

    async def _verify_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        snapshot: ReportSnapshotDE,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        reasons: list[str] = []

        if not isinstance(snapshot.summary_json, dict):
            reasons.append("summary_json_missing")
            checks.append({"Name": "summary_json_present", "IsValid": False})
        else:
            checks.append({"Name": "summary_json_present", "IsValid": True})

        if not isinstance(snapshot.provenance_json, dict):
            reasons.append("provenance_json_missing")
            checks.append({"Name": "provenance_json_present", "IsValid": False})
        else:
            checks.append({"Name": "provenance_json_present", "IsValid": True})

        manifest = self._build_manifest_from_snapshot(snapshot)
        computed_hash = self._sha256_hex(manifest)

        stored_hash = self._normalize_optional_text(snapshot.manifest_hash)
        has_stored_hash = stored_hash is not None
        checks.append({"Name": "manifest_hash_present", "IsValid": has_stored_hash})
        if not has_stored_hash:
            reasons.append("manifest_hash_missing")
        else:
            matches = stored_hash.lower() == computed_hash.lower()
            checks.append({"Name": "manifest_hash_match", "IsValid": matches})
            if not matches:
                reasons.append("manifest_hash_mismatch")

        if snapshot.signature_json is None:
            checks.append(
                {
                    "Name": "signature_present",
                    "IsValid": False,
                    "Skipped": True,
                }
            )
        elif not isinstance(snapshot.signature_json, Mapping):
            checks.append({"Name": "signature_shape", "IsValid": False})
            reasons.append("signature_json_invalid")
        else:
            checks.append({"Name": "signature_present", "IsValid": True})
            signature_ok, signature_reasons = await self._verify_signature(
                tenant_id=tenant_id,
                signature_json=snapshot.signature_json,
                manifest_hash=computed_hash,
            )
            checks.append({"Name": "signature_valid", "IsValid": signature_ok})
            reasons.extend(signature_reasons)

        is_valid = len(reasons) == 0
        return {
            "IsValid": is_valid,
            "Checks": checks,
            "Reasons": list(dict.fromkeys(reasons)),
            "ManifestHash": computed_hash,
        }

    async def action_verify_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ReportSnapshotVerifyValidation,
    ) -> tuple[dict[str, Any], int]:
        """Verify deterministic manifest and optional signature for a snapshot."""
        _ = entity_id
        _ = auth_user_id

        try:
            snapshot = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if snapshot is None:
            abort(404, "Report snapshot not found.")

        result = await self._verify_snapshot(
            tenant_id=tenant_id,
            snapshot=snapshot,
        )

        if bool(data.require_clean) and not bool(result["IsValid"]):
            abort(409, "Report snapshot verification failed.")

        return result, 200
