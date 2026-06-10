#!/usr/bin/env python3
"""Render an ECS task definition template from placeholder values."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


class RenderError(RuntimeError):
    """Raised when a task definition template cannot be rendered."""


def _coerce_placeholder_value(key: str, value: Any) -> str:
    """Return a non-empty string placeholder value."""
    if not isinstance(value, (str, int, float, bool)):
        raise RenderError(f"placeholder {key!r} must be a scalar value")
    result = str(value)
    if result == "":
        raise RenderError(f"placeholder {key!r} must not be empty")
    return result


def _validate_placeholder_name(key: str) -> None:
    """Validate a placeholder key without braces."""
    if not _PLACEHOLDER_RE.fullmatch("{{" + key + "}}"):
        raise RenderError(f"invalid placeholder name: {key!r}")


def parse_placeholder_assignment(raw: str) -> tuple[str, str]:
    """Parse a KEY=VALUE placeholder assignment."""
    key, separator, value = raw.partition("=")
    if not separator or not key:
        raise RenderError(f"invalid placeholder assignment: {raw!r}")
    _validate_placeholder_name(key)
    return key, _coerce_placeholder_value(key, value)


def load_extra_placeholders(path: Path) -> dict[str, str]:
    """Load extra placeholder values from a JSON object."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RenderError(f"unable to read extra placeholders file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RenderError(f"invalid extra placeholders JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RenderError("extra placeholders JSON must be an object")
    placeholders: dict[str, str] = {}
    for key, value in payload.items():
        _validate_placeholder_name(key)
        placeholders[key] = _coerce_placeholder_value(key, value)
    return placeholders


def load_env_placeholders(
    prefix: str,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Load placeholder values from environment variables with a prefix."""
    if not prefix:
        return {}
    source = os.environ if environ is None else environ
    placeholders: dict[str, str] = {}
    for name, value in source.items():
        if not name.startswith(prefix):
            continue
        key = name.removeprefix(prefix)
        _validate_placeholder_name(key)
        placeholders[key] = _coerce_placeholder_value(key, value)
    return placeholders


def _replace_placeholders(value: Any, placeholders: dict[str, str]) -> Any:
    """Replace placeholders recursively in a decoded JSON value."""
    if isinstance(value, dict):
        return {
            key: _replace_placeholders(item, placeholders)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _replace_placeholders(item, placeholders)
            for item in value
        ]
    if not isinstance(value, str):
        return value

    def replace_match(match: re.Match[str]) -> str:
        key = match.group(1)
        try:
            return placeholders[key]
        except KeyError as exc:
            raise RenderError(f"missing placeholder value: {key}") from exc

    return _PLACEHOLDER_RE.sub(replace_match, value)


def _find_unresolved(value: Any) -> list[str]:
    """Return unresolved placeholders in a decoded JSON value."""
    if isinstance(value, dict):
        unresolved: list[str] = []
        for item in value.values():
            unresolved.extend(_find_unresolved(item))
        return unresolved
    if isinstance(value, list):
        unresolved = []
        for item in value:
            unresolved.extend(_find_unresolved(item))
        return unresolved
    if isinstance(value, str):
        return _PLACEHOLDER_RE.findall(value)
    return []


def render_task_definition(
    *,
    template_path: Path,
    output_path: Path,
    placeholders: dict[str, str],
) -> None:
    """Render one ECS task definition template to JSON."""
    try:
        template = json.loads(template_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RenderError(f"unable to read task definition template: {template_path}") from exc
    except json.JSONDecodeError as exc:
        raise RenderError(f"invalid task definition template JSON: {template_path}") from exc

    rendered = _replace_placeholders(template, placeholders)
    unresolved = sorted(set(_find_unresolved(rendered)))
    if unresolved:
        raise RenderError(
            "unresolved task definition placeholder(s): "
            + ", ".join(unresolved)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(rendered, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--set", action="append", default=[], dest="assignments")
    parser.add_argument("--extra-json", action="append", default=[], type=Path)
    parser.add_argument("--env-prefix", default="")
    args = parser.parse_args(argv)

    try:
        placeholders = load_env_placeholders(args.env_prefix)
        for path in args.extra_json:
            placeholders.update(load_extra_placeholders(path))
        for assignment in args.assignments:
            key, value = parse_placeholder_assignment(assignment)
            placeholders[key] = value
        render_task_definition(
            template_path=args.template,
            output_path=args.output,
            placeholders=placeholders,
        )
    except RenderError as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
