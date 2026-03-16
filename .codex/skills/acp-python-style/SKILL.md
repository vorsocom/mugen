---
name: acp-python-style
description: Apply the formatting and structural conventions used in mugen/core/plugin/acp. Use when creating or modifying Python modules in ACP, or nearby plugin/test code that should match ACP style (for example mugen/core/plugin/audit and ACP-focused tests).
---

# ACP Python Style

## Overview
Match ACP formatting by copying the nearest ACP peer-file shape, then validate with this skill's checker before finalizing edits.

## Workflow
1. Choose a local ACP exemplar in the same layer before editing.
2. Mirror the exemplar's file scaffold: module docstring, optional `__all__`, import grouping, class/function layout, and multiline formatting.
3. Apply the concrete rules in `references/acp_style_guide.md`.
4. Run the style checker on changed files.
5. Fix reported style issues before returning final output.

## Validation Command
Run from repository root:

```bash
python .codex/skills/acp-python-style/scripts/check_acp_style.py <changed_file.py> [more_files.py]
```

The checker auto-detects max line length from `.vscode/settings.json` (Black args or rulers).
Use `--max-line-length` to override when needed.

To scan ACP as a whole:

```bash
python .codex/skills/acp-python-style/scripts/check_acp_style.py
```

## Operating Rules
- Prefer matching nearby ACP files over generic formatter output.
- Keep edits surgical; do not reformat unrelated files.
- Keep line length at the workspace formatter limit.
  Current repo config in `.vscode/settings.json` is Black `--line-length 88`.
- Use double-quoted strings to match ACP's prevailing style.
- Resolve model forward references for static analysis:
  Prefer `TYPE_CHECKING` imports for unsuppressed `Mapped["TypeName"]` annotations.
  Use inline `# type: ignore` only when a type-only import is not practical.
- Keep pylint pragmas in ACP format when needed (one directive per line).
- Re-run the checker after every non-trivial edit.

## References
- Style source of truth: `references/acp_style_guide.md`
- Automated checker: `scripts/check_acp_style.py`
