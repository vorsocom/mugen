---
name: prepush-quality-gates
description: Run mugen pre-push quality gates end-to-end. Use when you need a single repeatable check before commit/push that confirms full unit tests pass, full E2E template validations pass, and total coverage remains at 100%.
---

# Prepush Quality Gates

## Overview
Use this skill to run the full pre-push validation flow in one place:
1. Coverage-instrumented full unit test suite (`coverage run -m pytest mugen_test -q`)
2. Coverage check at 100%
3. E2E template validation run (`full` suite in `--mode full`, `smoke` suite in `--mode fast`)

## Command
Run from repository root:

```bash
bash .codex/skills/prepush-quality-gates/scripts/run_prepush_quality_gates.sh \
  --python /home/sando/.cache/pypoetry/virtualenvs/mugen-9ZxLq8_f-py3.12/bin/python \
  --mode full \
  --update-coverage-badge
```

Disposable database isolation is enabled by default.

To disable disposable DB for one run:

```bash
bash .codex/skills/prepush-quality-gates/scripts/run_prepush_quality_gates.sh \
  --python /home/sando/.cache/pypoetry/virtualenvs/mugen-9ZxLq8_f-py3.12/bin/python \
  --no-ephemeral-db
```

For fast inner-loop checks:

```bash
bash .codex/skills/prepush-quality-gates/scripts/run_prepush_quality_gates.sh \
  --python /home/sando/.cache/pypoetry/virtualenvs/mugen-9ZxLq8_f-py3.12/bin/python \
  --mode fast
```

If `--python` is omitted, the script uses `python`.

## Operating Rules
- Treat any non-zero exit as a hard gate failure.
- Keep the coverage gate at `--fail-under=100`.
- Use this flow immediately before commit/push for release-confidence checks.
