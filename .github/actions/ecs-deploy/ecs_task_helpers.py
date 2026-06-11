#!/usr/bin/env python3
"""Small ECS deploy helpers used by the composite GitHub Action."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from typing import Any


class DeployHelperError(RuntimeError):
    """Raised when an ECS deploy helper cannot complete safely."""


def _read_stdin_json() -> dict[str, Any]:
    """Read a JSON object from stdin."""
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DeployHelperError("stdin did not contain valid JSON") from exc
    if not isinstance(payload, dict):
        raise DeployHelperError("stdin JSON must be an object")
    return payload


def _json_diagnostic(payload: Any) -> str:
    """Return compact-but-readable JSON diagnostics."""
    return json.dumps(payload, indent=2, sort_keys=True)


def build_container_overrides(container_name: str, command_json: str) -> str:
    """Build an ECS run-task overrides payload."""
    try:
        command = json.loads(command_json)
    except json.JSONDecodeError as exc:
        raise DeployHelperError("task command must be valid JSON") from exc
    if not isinstance(command, list) or not all(
        isinstance(item, str)
        for item in command
    ):
        raise DeployHelperError(
            "task command must be a JSON array of strings",
        )
    return json.dumps(
        {
            "containerOverrides": [
                {
                    "name": container_name,
                    "command": command,
                },
            ],
        },
        separators=(",", ":"),
    )


def extract_started_task_arn(payload: dict[str, Any]) -> str:
    """Return the first task ARN from an ECS run-task response."""
    failures = payload.get("failures") or []
    if failures:
        raise DeployHelperError(
            "ECS run-task returned failures:\n"
            + _json_diagnostic(failures),
        )
    tasks = payload.get("tasks") or []
    if not tasks:
        raise DeployHelperError(
            "ECS run-task did not start a task:\n"
            + _json_diagnostic(payload),
        )
    task_arn = tasks[0].get("taskArn")
    if not isinstance(task_arn, str) or not task_arn:
        raise DeployHelperError(
            "ECS run-task response did not include taskArn:\n"
            + _json_diagnostic(payload),
        )
    return task_arn


def assert_container_exit_zero(
    *,
    payload: dict[str, Any],
    container_name: str,
) -> None:
    """Validate that the named container in a stopped task exited with zero."""
    tasks = payload.get("tasks") or []
    if not tasks:
        raise DeployHelperError(
            "one-off task disappeared before inspection:\n"
            + _json_diagnostic(payload),
        )
    task = tasks[0]
    for container in task.get("containers", []):
        if container.get("name") != container_name:
            continue
        exit_code = container.get("exitCode")
        if exit_code == 0:
            return
        reason = container.get("reason") or task.get("stoppedReason")
        detail = f" reason={reason!r}" if reason else ""
        raise DeployHelperError(
            f"one-off container exited with {exit_code!r}{detail}:\n"
            + _json_diagnostic(task),
        )
    raise DeployHelperError(
        f"container {container_name!r} not found in one-off task:\n"
        + _json_diagnostic(task),
    )


def assert_health_ok(*, url: str, attempts: int, delay_seconds: float) -> None:
    """Poll a JSON health endpoint until it returns {'status': 'ok'}."""
    last_error = "health endpoint was not checked"
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                body = response.read().decode("utf-8")
            payload = json.loads(body)
            if payload == {"status": "ok"}:
                return
            last_error = f"unexpected health payload: {payload!r}"
        except Exception as exc:  # noqa: BLE001 - command boundary
            last_error = str(exc)
        time.sleep(delay_seconds)
    raise DeployHelperError(f"health check failed for {url}: {last_error}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    overrides_parser = subparsers.add_parser("overrides")
    overrides_parser.add_argument("--container-name", required=True)
    overrides_parser.add_argument("--command-json", required=True)

    subparsers.add_parser("task-arn")

    exit_parser = subparsers.add_parser("assert-container-exit-zero")
    exit_parser.add_argument("--container-name", required=True)

    health_parser = subparsers.add_parser("assert-health")
    health_parser.add_argument("--url", required=True)
    health_parser.add_argument("--attempts", type=int, default=12)
    health_parser.add_argument("--delay-seconds", type=float, default=5.0)

    args = parser.parse_args(argv)
    try:
        if args.command == "overrides":
            print(
                build_container_overrides(
                    args.container_name,
                    args.command_json,
                ),
            )
        elif args.command == "task-arn":
            print(extract_started_task_arn(_read_stdin_json()))
        elif args.command == "assert-container-exit-zero":
            assert_container_exit_zero(
                payload=_read_stdin_json(),
                container_name=args.container_name,
            )
        elif args.command == "assert-health":
            assert_health_ok(
                url=args.url,
                attempts=args.attempts,
                delay_seconds=args.delay_seconds,
            )
        else:
            raise DeployHelperError(f"unknown helper command: {args.command}")
    except DeployHelperError as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
