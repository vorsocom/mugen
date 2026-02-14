#!/usr/bin/env python3
"""Check ACP-style formatting conventions on Python files."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path


DEFAULT_ROOT = "mugen/core/plugin/acp"
DEFAULT_MAX_LINE_LENGTH = 88
DEFAULT_WORKSPACE_SETTINGS = ".vscode/settings.json"


class Violation:
    """Represents a single style violation."""

    def __init__(self, path: Path, line: int, message: str) -> None:
        self.path = path
        self.line = line
        self.message = message

    def format(self) -> str:
        """Format violation in grep-friendly style."""
        return f"{self.path}:{self.line}: {self.message}"


def _collect_files(paths: list[str], acp_root: str) -> list[Path]:
    """Collect Python files from explicit inputs or ACP root by default."""
    candidates: list[Path] = []

    if paths:
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                candidates.extend(sorted(p.rglob("*.py")))
            elif p.suffix == ".py":
                candidates.append(p)
    else:
        candidates.extend(sorted(Path(acp_root).rglob("*.py")))

    out: list[Path] = []
    seen: set[Path] = set()
    for p in candidates:
        if "__pycache__" in p.parts:
            continue
        rp = p.resolve()
        if rp not in seen:
            out.append(p)
            seen.add(rp)

    return out


def _discover_max_line_length(settings_path: Path) -> int | None:
    """Read line-length preference from VS Code settings, if present."""
    if not settings_path.is_file():
        return None

    try:
        text = settings_path.read_text(encoding="utf-8")
    except OSError:
        return None

    # Prefer Black formatter args when present.
    for key in ("black-formatter.args", "python.formatting.blackArgs"):
        match = re.search(
            rf'"{re.escape(key)}"\s*:\s*\[(?P<body>.*?)\]',
            text,
            re.DOTALL,
        )
        if not match:
            continue

        line_len_match = re.search(
            r'"--line-length"\s*,\s*"?(?P<n>\d+)"?',
            match.group("body"),
            re.DOTALL,
        )
        if line_len_match:
            return int(line_len_match.group("n"))

    # Fallback to the first ruler value.
    match = re.search(r'"editor\.rulers"\s*:\s*\[(?P<body>[^\]]+)\]', text, re.DOTALL)
    if not match:
        return None

    ruler_match = re.search(r"\d+", match.group("body"))
    if ruler_match:
        return int(ruler_match.group(0))

    return None


def _check_first_statement_is_docstring(path: Path, lines: list[str]) -> Violation | None:
    """Ensure the first non-comment statement starts a docstring."""
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith('"""'):
            return None
        return Violation(path, line_no, "first statement should be a module docstring")
    return None


def _check_text_rules(path: Path, lines: list[str], max_len: int) -> list[Violation]:
    """Check simple text-level style rules."""
    violations: list[Violation] = []

    first_stmt_issue = _check_first_statement_is_docstring(path, lines)
    if first_stmt_issue is not None:
        violations.append(first_stmt_issue)

    for line_no, line in enumerate(lines, start=1):
        if "\t" in line:
            violations.append(Violation(path, line_no, "tab character found"))

        if line.rstrip(" \t") != line:
            violations.append(Violation(path, line_no, "trailing whitespace found"))

        if len(line) > max_len:
            violations.append(
                Violation(
                    path,
                    line_no,
                    f"line too long ({len(line)} > {max_len})",
                )
            )

    return violations


def _check_ast_rules(path: Path, text: str) -> list[Violation]:
    """Check AST-level conventions used in ACP files."""
    violations: list[Violation] = []

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        line = exc.lineno or 1
        violations.append(Violation(path, line, f"syntax error: {exc.msg}"))
        return violations

    if ast.get_docstring(tree, clean=False) is None:
        violations.append(Violation(path, 1, "module docstring missing"))

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            if ast.get_docstring(node, clean=False) is None:
                violations.append(
                    Violation(path, node.lineno, f"public class '{node.name}' missing docstring")
                )

    return violations


def check_file(path: Path, max_len: int) -> list[Violation]:
    """Run all style checks for one file."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [Violation(path, 1, "file is not valid UTF-8")]

    lines = text.splitlines()
    violations = _check_text_rules(path, lines, max_len)
    violations.extend(_check_ast_rules(path, text))
    return violations


def main() -> int:
    """Parse args, run checks, and print results."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Python files or directories to check. Defaults to ACP plugin root.",
    )
    parser.add_argument(
        "--acp-root",
        default=DEFAULT_ROOT,
        help=f"Default scan root when no explicit paths are provided (default: {DEFAULT_ROOT}).",
    )
    parser.add_argument(
        "--max-line-length",
        type=int,
        default=None,
        help=(
            "Maximum allowed line length. If omitted, the checker reads it from "
            ".vscode/settings.json and falls back to 88."
        ),
    )
    parser.add_argument(
        "--workspace-settings",
        default=DEFAULT_WORKSPACE_SETTINGS,
        help=(
            "Path to VS Code settings used for auto-detecting line length "
            f"(default: {DEFAULT_WORKSPACE_SETTINGS})."
        ),
    )
    args = parser.parse_args()

    workspace_max_len = _discover_max_line_length(Path(args.workspace_settings))
    max_line_length = (
        args.max_line_length
        if args.max_line_length is not None
        else workspace_max_len or DEFAULT_MAX_LINE_LENGTH
    )

    files = _collect_files(args.paths, args.acp_root)
    if not files:
        print("No Python files found to check.")
        return 1

    violations: list[Violation] = []
    for path in files:
        violations.extend(check_file(path, max_line_length))

    if violations:
        for item in violations:
            print(item.format())
        print(f"\nFound {len(violations)} ACP style violation(s) across {len(files)} file(s).")
        return 1

    print(f"ACP style check passed for {len(files)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
