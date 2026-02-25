# Migration Track Separation

Status: Accepted  
Last Updated: 2026-02-24  
Audience: Core maintainers and downstream plugin teams

## Decision

muGen now uses an explicit migration-track model:

- Core schema changes run in the `core` Alembic track.
- Downstream plugin schema changes run in plugin-owned tracks.
- Each track has independent versioning state (schema + version table).

This prevents downstream plugin revisions from branching core migration history
and avoids core deployments failing on plugin-only migration conflicts.

## Why

Previously, migrations ran from a single Alembic stream with one version table.
That made core and plugin revisions share a graph and could create:

- multi-head conflicts caused by unrelated plugin changes,
- coupling between core release cadence and plugin schema rollout,
- higher blast radius for migration failures.

## Model

### Core track

- Alembic config: `alembic.ini`
- Script location: `migrations/`
- Schema: `mugen`
- Version table: `mugen.alembic_version`

### Plugin tracks

Each downstream plugin owns:

- its own Alembic config/env/versions directory,
- its own schema (for example `acme_extension`),
- its own version table (for example `acme_extension.alembic_version`).

Template starter files are provided in:

- `migrations/plugin_track_template/`

## Runtime Contract

Use `scripts/run_migration_tracks.py` to execute migrations by track.
It sets track-specific Alembic env vars:

- `MUGEN_ALEMBIC_TRACK`
- `MUGEN_ALEMBIC_SCHEMA`
- `MUGEN_ALEMBIC_VERSION_TABLE`
- `MUGEN_ALEMBIC_VERSION_TABLE_SCHEMA`
- optional `MUGEN_ALEMBIC_MODEL_MODULES`

## Configuration Contract

Track configuration lives under `rdbms.migration_tracks` in `mugen.toml`.

```toml
[rdbms.migration_tracks.core]
enabled = true
alembic_config = "alembic.ini"
schema = "mugen"
version_table = "alembic_version"
version_table_schema = "mugen"

[[rdbms.migration_tracks.plugins]]
name = "acme_extension"
enabled = true
alembic_config = "plugins/acme_extension/alembic.ini"
schema = "acme_extension"
version_table = "alembic_version"
version_table_schema = "acme_extension"
model_modules = ["acme_extension.model.base"]
```

## Standard Commands

Run all enabled tracks:

```bash
python scripts/run_migration_tracks.py upgrade head
```

Run a specific track:

```bash
python scripts/run_migration_tracks.py --track core upgrade head
python scripts/run_migration_tracks.py --track acme_extension upgrade head
```

## Downstream Plugin Onboarding

1. Copy `migrations/plugin_track_template/` into your plugin migration folder.
2. Add a plugin track entry in `rdbms.migration_tracks.plugins`.
3. Keep plugin revisions in plugin-owned `versions/`, not in core `migrations/versions`.
4. Run migration checks per track in CI.

## Legacy Note

Historical revisions remain in the existing core lineage. This decision applies
to new downstream plugin schema work going forward.
