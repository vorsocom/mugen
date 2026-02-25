# Plugin Migration Track Template

This template is for downstream plugins that must keep schema and migration
history independent from core.

## Intended layout

Copy this folder to your plugin package/repo as `<plugin>/migrations`:

- `alembic.ini`
- `env.py`
- `script.py.mako`
- `versions/`

## Required runtime environment

The migration runner sets these automatically:

- `MUGEN_ALEMBIC_TRACK`
- `MUGEN_ALEMBIC_SCHEMA`
- `MUGEN_ALEMBIC_VERSION_TABLE`
- `MUGEN_ALEMBIC_VERSION_TABLE_SCHEMA`

The template reads DB URL from `mugen.toml` at:

- `rdbms.alembic.url`

## Optional autogenerate metadata

Set `MUGEN_ALEMBIC_METADATA_MODULE` to a module path exporting SQLAlchemy
`MetaData` in a top-level `metadata` symbol.

Example:

```bash
export MUGEN_ALEMBIC_METADATA_MODULE="acme_plugin.model.base"
python -m alembic -c plugins/acme/alembic.ini revision --autogenerate -m "..."
```
