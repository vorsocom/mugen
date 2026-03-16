"""Run audit lifecycle phases in one-shot or looping worker mode."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import uuid

from mugen import bootstrap_app, create_quart_app
from mugen.core import di
from mugen.core.plugin.audit.api.validation import AuditEventRunLifecycleValidation


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run audit lifecycle phases for tenant or non-tenant audit rows.",
    )
    parser.add_argument(
        "--tenant-id",
        help="Optional tenant UUID; omit to run non-tenant scope only.",
    )
    parser.add_argument(
        "--actor-id",
        default="00000000-0000-0000-0000-000000000000",
        help="Actor UUID recorded for action invocation context.",
    )
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--now-override",
        default=None,
        help="Optional ISO timestamp override (test-only).",
    )
    parser.add_argument(
        "--phases",
        default=None,
        help=(
            "Comma-separated phases from "
            "seal_backlog,redact_due,tombstone_expired,purge_due."
        ),
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=0.0,
        help="Loop interval in seconds. Use 0 for one-shot mode.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of loops to run. Use 0 for infinite loop mode.",
    )
    return parser.parse_args()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_phases(value: str | None) -> list[str] | None:
    if value is None:
        return None
    phases = [phase.strip() for phase in value.split(",")]
    phases = [phase for phase in phases if phase]
    return phases or None


async def _run_once(args: argparse.Namespace) -> dict:
    actor_id = uuid.UUID(str(args.actor_id))
    tenant_id = uuid.UUID(str(args.tenant_id)) if args.tenant_id else None

    payload = AuditEventRunLifecycleValidation(
        batch_size=args.batch_size,
        max_batches=args.max_batches,
        dry_run=bool(args.dry_run),
        now_override=_parse_datetime(args.now_override),
        phases=_parse_phases(args.phases),
    )

    registry = di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)
    resource = registry.get_resource("AuditEvents")
    service = registry.get_edm_service(resource.service_key)

    if tenant_id is None:
        result, _status = await service.entity_set_action_run_lifecycle(
            auth_user_id=actor_id,
            data=payload,
        )
        return result

    result, _status = await service.action_run_lifecycle(
        tenant_id=tenant_id,
        where={"tenant_id": tenant_id},
        auth_user_id=actor_id,
        data=payload,
    )
    return result


async def _main() -> None:
    args = _parse_args()
    app = create_quart_app()

    async with app.app_context():
        await bootstrap_app(app)

        runs = 0
        while True:
            result = await _run_once(args)
            print(json.dumps(result, default=str, sort_keys=True))  # noqa: T201

            runs += 1
            if args.interval_seconds <= 0:
                break
            if args.iterations > 0 and runs >= args.iterations:
                break

            await asyncio.sleep(args.interval_seconds)


if __name__ == "__main__":
    asyncio.run(_main())
