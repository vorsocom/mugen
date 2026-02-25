"""Run SLA tick and escalation execute loops in one-shot or worker mode."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import uuid

from mugen import bootstrap_app, create_quart_app
from mugen.core import di
from mugen.core.plugin.ops_sla.api.validation import (
    SlaClockTickValidation,
    SlaEscalationExecuteValidation,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run ops execution core worker loops: "
            "OpsSlaClocks/$action/tick -> OpsSlaEscalationPolicies/$action/execute"
        ),
    )
    parser.add_argument(
        "--tenant-id",
        help="Optional tenant UUID; omit to run across all tenants.",
    )
    parser.add_argument(
        "--actor-id",
        default="00000000-0000-0000-0000-000000000000",
        help="Actor UUID recorded for action invocation context.",
    )
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument(
        "--now-override",
        default=None,
        help="Optional ISO timestamp override for deterministic testing.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=30.0,
        help="Loop interval in seconds. Use <=0 for one-shot mode.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of loop iterations. Use 0 for infinite loop mode.",
    )
    return parser.parse_args()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def _tenant_ids(args: argparse.Namespace) -> list[uuid.UUID]:
    if args.tenant_id:
        return [uuid.UUID(str(args.tenant_id))]

    registry = di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)
    tenant_resource = registry.get_resource("Tenants")
    tenant_service = registry.get_edm_service(tenant_resource.service_key)
    rows = await tenant_service.list()

    tenant_ids: list[uuid.UUID] = []
    for row in rows:
        tenant_id = getattr(row, "id", None)
        if isinstance(tenant_id, uuid.UUID):
            tenant_ids.append(tenant_id)

    return tenant_ids


def _build_trigger_events(tenant_id: uuid.UUID, tick_result: dict) -> list[dict]:
    trigger_events: list[dict] = []

    for warned in tick_result.get("Warned", []):
        trigger_events.append(
            {
                "TenantId": str(tenant_id),
                "ClockId": warned.get("ClockId"),
                "ClockEventId": warned.get("ClockEventId"),
                "EventType": "warned",
                "WarnedOffsetSeconds": warned.get("WarnedOffsetSeconds"),
                "TraceId": warned.get("TraceId"),
            }
        )

    for breached in tick_result.get("Breached", []):
        trigger_events.append(
            {
                "TenantId": str(tenant_id),
                "ClockId": breached.get("ClockId"),
                "ClockEventId": breached.get("ClockEventId"),
                "EventType": "breached",
                "TraceId": breached.get("TraceId"),
            }
        )

    return trigger_events


async def _run_for_tenant(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    args: argparse.Namespace,
) -> dict:
    registry = di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)

    clock_resource = registry.get_resource("OpsSlaClocks")
    clock_service = registry.get_edm_service(clock_resource.service_key)

    escalation_resource = registry.get_resource("OpsSlaEscalationPolicies")
    escalation_service = registry.get_edm_service(escalation_resource.service_key)

    tick_payload = SlaClockTickValidation(
        batch_size=args.batch_size,
        now_utc=_parse_datetime(args.now_override),
        dry_run=bool(args.dry_run),
    )
    tick_result, _tick_status = await clock_service.action_tick(
        tenant_id=tenant_id,
        where={"tenant_id": tenant_id},
        auth_user_id=actor_id,
        data=tick_payload,
    )

    escalation_results: list[dict] = []
    trigger_events = _build_trigger_events(tenant_id, tick_result)
    for trigger_event in trigger_events:
        execute_payload = SlaEscalationExecuteValidation(
            trigger_event_json=trigger_event,
            dry_run=bool(args.dry_run),
        )
        execute_result, _execute_status = await escalation_service.action_execute(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=actor_id,
            data=execute_payload,
        )
        escalation_results.append(execute_result)

    return {
        "TenantId": str(tenant_id),
        "Tick": tick_result,
        "EscalationExecute": escalation_results,
    }


async def _run_once(args: argparse.Namespace) -> dict:
    actor_id = uuid.UUID(str(args.actor_id))
    tenants = await _tenant_ids(args)

    runs: list[dict] = []
    for tenant_id in tenants:
        runs.append(
            await _run_for_tenant(
                tenant_id=tenant_id,
                actor_id=actor_id,
                args=args,
            )
        )

    return {
        "TenantCount": len(tenants),
        "Runs": runs,
    }


async def _main() -> None:
    args = _parse_args()
    app = create_quart_app()

    async with app.app_context():
        await bootstrap_app(app)

        run_count = 0
        while True:
            summary = await _run_once(args)
            print(json.dumps(summary, default=str, sort_keys=True))  # noqa: T201

            run_count += 1
            if args.interval_seconds <= 0:
                break
            if args.iterations > 0 and run_count >= args.iterations:
                break

            await asyncio.sleep(args.interval_seconds)


if __name__ == "__main__":
    asyncio.run(_main())
