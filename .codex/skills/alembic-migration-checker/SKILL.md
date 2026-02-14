---
name: alembic-migration-checker
description: Assess Alembic migration correctness and consistency in mugen. Use when reviewing migration quality before running migrations, or when debugging migration failures. Runs revision graph checks, static revision checks, offline SQL generation, duplicate CREATE TYPE detection, and optional disposable Postgres upgrade/downgrade roundtrip.
---

# Alembic Migration Checker

## Overview
Use this skill to run a repeatable migration-quality assessment before shipping or executing migrations.

## Workflow
1. Run the checker script in quick mode to validate graph, revision structure, and offline SQL.
2. If quick mode passes, run with `--roundtrip` to verify real `upgrade head` + `downgrade base` in a disposable local Postgres cluster.
3. Treat failures as blockers; treat warnings as follow-up risk items.

## Commands
Run from repository root:

```bash
python .codex/skills/alembic-migration-checker/scripts/check_alembic_migrations.py
```

Full assessment including disposable DB roundtrip:

```bash
python .codex/skills/alembic-migration-checker/scripts/check_alembic_migrations.py --roundtrip
```

Use the project venv interpreter when needed:

```bash
<path-to-venv>/bin/python \
  .codex/skills/alembic-migration-checker/scripts/check_alembic_migrations.py --roundtrip
```

## Script Behavior
- Verifies `alembic heads` and `alembic history`.
- Parses every revision file under `migrations/versions`.
- Checks each revision has a `downgrade()` function.
- Generates `upgrade head --sql` and scans for duplicate `CREATE TYPE`.
- Optional `--roundtrip`:
  uses temporary Postgres data dir under `/tmp`, overrides DB URL in `mugen.toml`,
  runs `upgrade head` then `downgrade base`, validates version table cleanup, and restores config.

## Operating Rules
- Keep migration assessment read-heavy; do not edit migrations inside this skill workflow unless explicitly requested.
- Always report findings with severity and file paths.
- If roundtrip cannot run (missing `initdb`/`pg_ctl`/`psql`), report as a validation gap.
