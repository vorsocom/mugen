"""Shared durable ingress worker for external messaging platforms."""

from __future__ import annotations

__all__ = ["DefaultMessagingIngressService"]

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ingress import (
    IMessagingIngressService,
    MessagingIngressCheckpointUpdate,
    MessagingIngressEvent,
    MessagingIngressStageEntry,
    MessagingIngressStageResult,
)
from mugen.core.contract.service.ipc import IIPCService, IPCCommandRequest
from mugen.core.utility.config_value import (
    parse_nonnegative_finite_float,
    parse_optional_positive_int,
)
from mugen.core.utility.rdbms_schema import resolve_core_rdbms_schema


class DefaultMessagingIngressService(IMessagingIngressService):
    """SQL-backed durable ingress queue with shared IPC worker semantics."""

    _default_worker_poll_seconds = 0.5
    _default_worker_lease_seconds = 60
    _default_worker_batch_size = 50
    _default_max_attempts = 5

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
        relational_runtime: Any,
        ipc_service: IIPCService,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._runtime = relational_runtime
        self._ipc_service = ipc_service
        self._core_schema = resolve_core_rdbms_schema(config)
        self._worker_poll_seconds = self._resolve_worker_poll_seconds()
        self._worker_lease_seconds = self._resolve_worker_lease_seconds()
        self._worker_batch_size = self._resolve_worker_batch_size()
        self._max_attempts = self._resolve_max_attempts()
        self._worker_task: asyncio.Task | None = None
        self._worker_stop = asyncio.Event()
        self._worker_lock = asyncio.Lock()

        session_maker: async_sessionmaker = self._runtime.session_maker

        @asynccontextmanager
        async def _session_provider():
            async with session_maker() as session:
                async with session.begin():
                    yield session

        self._session_provider = _session_provider

    def _schema_sql(self, statement: str):
        return sa_text(statement.replace("mugen.", f"{self._core_schema}."))

    def _ingress_config(self) -> SimpleNamespace:
        cfg = getattr(self._config, "ingress", None)
        return cfg if isinstance(cfg, SimpleNamespace) else SimpleNamespace()

    def _resolve_worker_poll_seconds(self) -> float:
        raw_value = getattr(
            self._ingress_config(),
            "worker_poll_seconds",
            self._default_worker_poll_seconds,
        )
        return parse_nonnegative_finite_float(
            raw_value,
            "ingress.worker_poll_seconds",
            default=self._default_worker_poll_seconds,
        )

    def _resolve_worker_lease_seconds(self) -> int:
        raw_value = getattr(
            self._ingress_config(),
            "worker_lease_seconds",
            self._default_worker_lease_seconds,
        )
        parsed = parse_optional_positive_int(
            raw_value,
            "ingress.worker_lease_seconds",
        )
        return self._default_worker_lease_seconds if parsed is None else parsed

    def _resolve_worker_batch_size(self) -> int:
        raw_value = getattr(
            self._ingress_config(),
            "worker_batch_size",
            self._default_worker_batch_size,
        )
        parsed = parse_optional_positive_int(
            raw_value,
            "ingress.worker_batch_size",
        )
        return self._default_worker_batch_size if parsed is None else parsed

    def _resolve_max_attempts(self) -> int:
        raw_value = getattr(
            self._ingress_config(),
            "max_attempts",
            self._default_max_attempts,
        )
        parsed = parse_optional_positive_int(
            raw_value,
            "ingress.max_attempts",
        )
        return self._default_max_attempts if parsed is None else parsed

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    async def check_readiness(self) -> None:
        async with self._runtime.engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
            result = await conn.execute(
                self._schema_sql(
                    "SELECT "
                    "to_regclass('mugen.messaging_ingress_event') AS messaging_ingress_event, "
                    "to_regclass('mugen.messaging_ingress_dedup') AS messaging_ingress_dedup, "
                    "to_regclass('mugen.messaging_ingress_dead_letter') AS messaging_ingress_dead_letter, "
                    "to_regclass('mugen.messaging_ingress_checkpoint') AS messaging_ingress_checkpoint"
                )
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise RuntimeError("Messaging ingress readiness query failed.")
        missing = [
            table_name
            for table_name in (
                "messaging_ingress_event",
                "messaging_ingress_dedup",
                "messaging_ingress_dead_letter",
                "messaging_ingress_checkpoint",
            )
            if row.get(table_name) in [None, ""]
        ]
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise RuntimeError(
                "Database schema is not ready. "
                "Run migrations before startup. "
                "Missing messaging ingress table(s): "
                f"{missing_text}."
            )

    async def ensure_started(self) -> None:
        async with self._worker_lock:
            if self._worker_task is not None and not self._worker_task.done():
                return
            self._worker_stop = asyncio.Event()
            self._worker_task = asyncio.create_task(
                self._worker_loop(),
                name="mugen.messaging_ingress.worker",
            )

    async def stage(
        self,
        entries: list[MessagingIngressStageEntry],
        *,
        checkpoints: list[MessagingIngressCheckpointUpdate] | None = None,
    ) -> MessagingIngressStageResult:
        if not isinstance(entries, list):
            raise TypeError("stage entries must be a list.")
        normalized_entries = [
            entry for entry in entries if isinstance(entry, MessagingIngressStageEntry)
        ]
        if len(normalized_entries) != len(entries):
            raise TypeError("stage entries must contain MessagingIngressStageEntry values.")
        normalized_checkpoints = checkpoints or []
        if not isinstance(normalized_checkpoints, list):
            raise TypeError("stage checkpoints must be a list when provided.")
        if any(
            not isinstance(item, MessagingIngressCheckpointUpdate)
            for item in normalized_checkpoints
        ):
            raise TypeError(
                "stage checkpoints must contain MessagingIngressCheckpointUpdate values."
            )

        await self.ensure_started()

        staged_count = 0
        duplicate_count = 0
        checkpoint_count = 0

        async with self._session_provider() as session:
            for entry in normalized_entries:
                dedupe_inserted = await self._insert_dedup_row(
                    session,
                    entry=entry,
                )
                if dedupe_inserted is not True:
                    duplicate_count += 1
                    continue
                await self._insert_event_row(
                    session,
                    entry=entry,
                )
                staged_count += 1

            for checkpoint in normalized_checkpoints:
                await self._upsert_checkpoint_row(
                    session,
                    checkpoint=checkpoint,
                )
                checkpoint_count += 1

        return MessagingIngressStageResult(
            staged_count=staged_count,
            duplicate_count=duplicate_count,
            checkpoint_count=checkpoint_count,
        )

    async def aclose(self) -> None:
        async with self._worker_lock:
            task = self._worker_task
            self._worker_task = None
            self._worker_stop.set()
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def get_checkpoint(
        self,
        *,
        platform: str,
        runtime_profile_key: str,
        checkpoint_key: str,
    ) -> str | None:
        async with self._session_provider() as session:
            result = await session.execute(
                self._schema_sql(
                    "SELECT checkpoint_value "
                    "FROM mugen.messaging_ingress_checkpoint "
                    "WHERE platform = :platform "
                    "AND runtime_profile_key = :runtime_profile_key "
                    "AND checkpoint_key = :checkpoint_key"
                ),
                {
                    "platform": platform,
                    "runtime_profile_key": runtime_profile_key,
                    "checkpoint_key": checkpoint_key,
                },
            )
            row = result.mappings().one_or_none()
        if row is None:
            return None
        value = row.get("checkpoint_value")
        return str(value) if isinstance(value, str) and value.strip() != "" else None

    async def _insert_dedup_row(
        self,
        session,
        *,
        entry: MessagingIngressStageEntry,
    ) -> bool:
        now = self._utc_now()
        event = entry.event
        result = await session.execute(
            self._schema_sql(
                "INSERT INTO mugen.messaging_ingress_dedup ("
                "platform, runtime_profile_key, event_type, dedupe_key, event_id, "
                "last_seen_at, expires_at"
                ") VALUES ("
                ":platform, :runtime_profile_key, :event_type, :dedupe_key, :event_id, "
                ":last_seen_at, :expires_at"
                ") "
                "ON CONFLICT (platform, runtime_profile_key, dedupe_key) DO NOTHING "
                "RETURNING id"
            ),
            {
                "platform": event.platform,
                "runtime_profile_key": event.runtime_profile_key,
                "event_type": event.event_type,
                "dedupe_key": event.dedupe_key,
                "event_id": event.event_id,
                "last_seen_at": now,
                "expires_at": now + timedelta(seconds=entry.dedupe_ttl_seconds),
            },
        )
        inserted = result.scalar_one_or_none()
        if inserted is not None:
            return True
        await session.execute(
            self._schema_sql(
                "UPDATE mugen.messaging_ingress_dedup "
                "SET event_id = COALESCE(:event_id, event_id), "
                "last_seen_at = :last_seen_at, "
                "expires_at = :expires_at, "
                "updated_at = now(), "
                "row_version = row_version + 1 "
                "WHERE platform = :platform "
                "AND runtime_profile_key = :runtime_profile_key "
                "AND dedupe_key = :dedupe_key"
            ),
            {
                "platform": event.platform,
                "runtime_profile_key": event.runtime_profile_key,
                "dedupe_key": event.dedupe_key,
                "event_id": event.event_id,
                "last_seen_at": now,
                "expires_at": now + timedelta(seconds=entry.dedupe_ttl_seconds),
            },
        )
        return False

    async def _insert_event_row(
        self,
        session,
        *,
        entry: MessagingIngressStageEntry,
    ) -> None:
        event = entry.event
        await session.execute(
            self._schema_sql(
                "INSERT INTO mugen.messaging_ingress_event ("
                "version, platform, runtime_profile_key, ipc_command, source_mode, "
                "event_type, event_id, dedupe_key, identifier_type, identifier_value, "
                "room_id, sender, payload, provider_context, received_at, status, attempts"
                ") VALUES ("
                ":version, :platform, :runtime_profile_key, :ipc_command, :source_mode, "
                ":event_type, :event_id, :dedupe_key, :identifier_type, :identifier_value, "
                ":room_id, :sender, :payload, :provider_context, :received_at, 'queued', 0"
                ")"
            ),
            {
                "version": event.version,
                "platform": event.platform,
                "runtime_profile_key": event.runtime_profile_key,
                "ipc_command": entry.ipc_command,
                "source_mode": event.source_mode,
                "event_type": event.event_type,
                "event_id": event.event_id,
                "dedupe_key": event.dedupe_key,
                "identifier_type": event.identifier_type,
                "identifier_value": event.identifier_value,
                "room_id": event.room_id,
                "sender": event.sender,
                "payload": dict(event.payload),
                "provider_context": dict(event.provider_context),
                "received_at": event.received_at,
            },
        )

    async def _upsert_checkpoint_row(
        self,
        session,
        *,
        checkpoint: MessagingIngressCheckpointUpdate,
    ) -> None:
        await session.execute(
            self._schema_sql(
                "INSERT INTO mugen.messaging_ingress_checkpoint ("
                "platform, runtime_profile_key, checkpoint_key, checkpoint_value, "
                "provider_context, observed_at"
                ") VALUES ("
                ":platform, :runtime_profile_key, :checkpoint_key, :checkpoint_value, "
                ":provider_context, :observed_at"
                ") "
                "ON CONFLICT (platform, runtime_profile_key, checkpoint_key) "
                "DO UPDATE SET "
                "checkpoint_value = EXCLUDED.checkpoint_value, "
                "provider_context = EXCLUDED.provider_context, "
                "observed_at = EXCLUDED.observed_at, "
                "updated_at = now(), "
                "row_version = mugen.messaging_ingress_checkpoint.row_version + 1"
            ),
            {
                "platform": checkpoint.platform,
                "runtime_profile_key": checkpoint.runtime_profile_key,
                "checkpoint_key": checkpoint.checkpoint_key,
                "checkpoint_value": checkpoint.checkpoint_value,
                "provider_context": dict(checkpoint.provider_context),
                "observed_at": checkpoint.observed_at,
            },
        )

    async def _worker_loop(self) -> None:
        try:
            while self._worker_stop.is_set() is not True:
                rows = await self._claim_batch()
                if not rows:
                    await asyncio.sleep(self._worker_poll_seconds)
                    continue
                for row in rows:
                    try:
                        await self._dispatch_claimed_row(row)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        self._logging_gateway.error(
                            "Messaging ingress worker dispatch failed "
                            f"(event_id={row.get('id')} error_type={type(exc).__name__} "
                            f"error={exc})."
                        )
        except asyncio.CancelledError:
            raise

    async def _claim_batch(self) -> list[dict[str, Any]]:
        lease_expires_at = self._utc_now() + timedelta(seconds=self._worker_lease_seconds)
        async with self._session_provider() as session:
            result = await session.execute(
                self._schema_sql(
                    "WITH claimable AS ("
                    "SELECT id "
                    "FROM mugen.messaging_ingress_event "
                    "WHERE status IN ('queued', 'processing') "
                    "AND (status = 'queued' OR lease_expires_at IS NULL OR lease_expires_at < now()) "
                    "ORDER BY received_at, created_at "
                    "FOR UPDATE SKIP LOCKED "
                    "LIMIT :batch_size"
                    ") "
                    "UPDATE mugen.messaging_ingress_event AS target "
                    "SET status = 'processing', "
                    "lease_expires_at = :lease_expires_at, "
                    "attempts = target.attempts + 1, "
                    "error_code = NULL, "
                    "error_message = NULL, "
                    "updated_at = now(), "
                    "row_version = target.row_version + 1 "
                    "FROM claimable "
                    "WHERE target.id = claimable.id "
                    "RETURNING target.*"
                ),
                {
                    "batch_size": self._worker_batch_size,
                    "lease_expires_at": lease_expires_at,
                },
            )
            return [dict(row) for row in result.mappings().all()]

    def _build_event_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        event = MessagingIngressEvent(
            version=int(row.get("version") or 1),
            platform=str(row.get("platform") or ""),
            runtime_profile_key=str(row.get("runtime_profile_key") or ""),
            source_mode=str(row.get("source_mode") or ""),
            event_type=str(row.get("event_type") or ""),
            event_id=row.get("event_id"),
            dedupe_key=str(row.get("dedupe_key") or ""),
            identifier_type=str(row.get("identifier_type") or ""),
            identifier_value=row.get("identifier_value"),
            room_id=row.get("room_id"),
            sender=row.get("sender"),
            payload=row.get("payload") if isinstance(row.get("payload"), dict) else {},
            provider_context=(
                row.get("provider_context")
                if isinstance(row.get("provider_context"), dict)
                else {}
            ),
            received_at=row.get("received_at"),
        )
        return event.to_dict()

    async def _dispatch_claimed_row(self, row: dict[str, Any]) -> None:
        request = IPCCommandRequest(
            platform=str(row.get("platform") or ""),
            command=str(row.get("ipc_command") or ""),
            data=self._build_event_payload(row),
        )
        try:
            result = await self._ipc_service.handle_ipc_request(request)
            errors = getattr(result, "errors", [])
            if errors:
                first_error = errors[0]
                code = getattr(first_error, "code", "handler_error")
                error = getattr(first_error, "error", "IPC handler returned an error.")
                await self._mark_failed(
                    row=row,
                    reason_code=str(code or "handler_error"),
                    error_message=str(error or "IPC handler returned an error."),
                )
                return
            await self._mark_completed(row_id=row["id"])
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await self._mark_failed(
                row=row,
                reason_code=type(exc).__name__,
                error_message=str(exc),
            )

    async def _mark_completed(self, *, row_id: object) -> None:
        async with self._session_provider() as session:
            await session.execute(
                self._schema_sql(
                    "UPDATE mugen.messaging_ingress_event "
                    "SET status = 'completed', "
                    "lease_expires_at = NULL, "
                    "completed_at = now(), "
                    "error_code = NULL, "
                    "error_message = NULL, "
                    "updated_at = now(), "
                    "row_version = row_version + 1 "
                    "WHERE id = :row_id"
                ),
                {"row_id": row_id},
            )

    async def _mark_failed(
        self,
        *,
        row: dict[str, Any],
        reason_code: str,
        error_message: str,
    ) -> None:
        attempts = int(row.get("attempts") or 0)
        first_failed_at = self._utc_now()
        async with self._session_provider() as session:
            if attempts >= self._max_attempts:
                await session.execute(
                    self._schema_sql(
                        "INSERT INTO mugen.messaging_ingress_dead_letter ("
                        "source_event_id, version, platform, runtime_profile_key, ipc_command, "
                        "source_mode, event_type, event_id, dedupe_key, identifier_type, "
                        "identifier_value, room_id, sender, payload, provider_context, "
                        "received_at, reason_code, error_message, status, attempts, "
                        "first_failed_at, last_failed_at"
                        ") VALUES ("
                        ":source_event_id, :version, :platform, :runtime_profile_key, "
                        ":ipc_command, :source_mode, :event_type, :event_id, :dedupe_key, "
                        ":identifier_type, :identifier_value, :room_id, :sender, :payload, "
                        ":provider_context, :received_at, :reason_code, :error_message, "
                        "'queued', :attempts, :first_failed_at, :last_failed_at"
                        ")"
                    ),
                    {
                        "source_event_id": row.get("id"),
                        "version": int(row.get("version") or 1),
                        "platform": row.get("platform"),
                        "runtime_profile_key": row.get("runtime_profile_key"),
                        "ipc_command": row.get("ipc_command"),
                        "source_mode": row.get("source_mode"),
                        "event_type": row.get("event_type"),
                        "event_id": row.get("event_id"),
                        "dedupe_key": row.get("dedupe_key"),
                        "identifier_type": row.get("identifier_type"),
                        "identifier_value": row.get("identifier_value"),
                        "room_id": row.get("room_id"),
                        "sender": row.get("sender"),
                        "payload": row.get("payload") if isinstance(row.get("payload"), dict) else {},
                        "provider_context": (
                            row.get("provider_context")
                            if isinstance(row.get("provider_context"), dict)
                            else {}
                        ),
                        "received_at": row.get("received_at"),
                        "reason_code": reason_code,
                        "error_message": error_message,
                        "attempts": attempts,
                        "first_failed_at": first_failed_at,
                        "last_failed_at": first_failed_at,
                    },
                )
                await session.execute(
                    self._schema_sql(
                        "UPDATE mugen.messaging_ingress_event "
                        "SET status = 'failed', "
                        "lease_expires_at = NULL, "
                        "error_code = :reason_code, "
                        "error_message = :error_message, "
                        "updated_at = now(), "
                        "row_version = row_version + 1 "
                        "WHERE id = :row_id"
                    ),
                    {
                        "row_id": row.get("id"),
                        "reason_code": reason_code,
                        "error_message": error_message,
                    },
                )
                return

            await session.execute(
                self._schema_sql(
                    "UPDATE mugen.messaging_ingress_event "
                    "SET status = 'queued', "
                    "lease_expires_at = NULL, "
                    "error_code = :reason_code, "
                    "error_message = :error_message, "
                    "updated_at = now(), "
                    "row_version = row_version + 1 "
                    "WHERE id = :row_id"
                ),
                {
                    "row_id": row.get("id"),
                    "reason_code": reason_code,
                    "error_message": error_message,
                },
            )
