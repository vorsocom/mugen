"""Verify ingress collision protection against disposable PostgreSQL storage."""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

from mugen.core.plugin.channel_orchestration.model.ingress_binding import IngressBinding


class TestIngressBindingPostgres(unittest.TestCase):
    """Exercise the actual migration and PostgreSQL partial CITEXT unique index."""

    def test_cross_tenant_insert_update_activation_and_migration_collision(self):
        initdb = shutil.which("initdb") or "/usr/lib/postgresql/16/bin/initdb"
        pg_ctl = shutil.which("pg_ctl") or "/usr/lib/postgresql/16/bin/pg_ctl"
        if not Path(initdb).is_file() or not Path(pg_ctl).is_file():
            self.skipTest("Disposable PostgreSQL server tools are unavailable.")
        index = next(
            item
            for item in IngressBinding.__table__.indexes
            if item.name == "ux_chorch_ingress_binding__ci_active_unique"
        )
        self.assertEqual(
            [column.name for column in index.columns],
            ["channel_key", "identifier_type", "identifier_value"],
        )
        migration_path = Path(__file__).resolve().parents[1] / (
            "migrations/versions/"
            "d8f2b6c4a0e1_ingress_binding_global_identifier_uniqueness.py"
        )
        spec = importlib.util.spec_from_file_location(
            "ingress_security_migration", migration_path
        )
        migration = importlib.util.module_from_spec(spec)
        with patch.dict("os.environ", {"MUGEN_ALEMBIC_SCHEMA": "ingress_security"}):
            spec.loader.exec_module(migration)

        with tempfile.TemporaryDirectory(prefix="mugen_ingress_pg_") as temp:
            data_dir = str(Path(temp) / "data")
            subprocess.run(
                [initdb, "-D", data_dir, "-A", "trust"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    pg_ctl,
                    "-D",
                    data_dir,
                    "-l",
                    str(Path(temp) / "postgres.log"),
                    "-o",
                    f"-c listen_addresses='' -c unix_socket_directories='{temp}'",
                    "start",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            try:
                engine = sa.create_engine(
                    sa.URL.create(
                        "postgresql+psycopg", database="postgres", query={"host": temp}
                    )
                )
                try:
                    self._verify_database(engine, migration)
                finally:
                    engine.dispose()
            finally:
                subprocess.run(
                    [pg_ctl, "-D", data_dir, "-m", "fast", "stop"],
                    check=True,
                    capture_output=True,
                    text=True,
                )

    def _verify_database(self, engine, migration):
        table = "ingress_security.channel_orchestration_ingress_binding"
        first_tenant, second_tenant = str(uuid.uuid4()), str(uuid.uuid4())
        insert = sa.text(f"""
            INSERT INTO {table} (tenant_id, channel_key, identifier_type,
                                 identifier_value, is_active)
            VALUES (:tenant, 'whatsapp', 'phone_number_id', :value, :active)
        """)
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE EXTENSION citext"))
            connection.execute(sa.text("CREATE SCHEMA ingress_security"))
            connection.execute(sa.text(f"""
                CREATE TABLE {table} (
                    tenant_id uuid NOT NULL, channel_key citext NOT NULL,
                    identifier_type citext NOT NULL, identifier_value citext NOT NULL,
                    is_active boolean NOT NULL
                )
            """))
            connection.execute(sa.text(f"""
                CREATE UNIQUE INDEX ux_chorch_ingress_binding__tci_active_unique
                ON {table} (tenant_id, channel_key, identifier_type, identifier_value)
                WHERE is_active = true
            """))
            connection.execute(
                insert, {"tenant": first_tenant, "value": "Victim", "active": True}
            )
            connection.execute(
                insert, {"tenant": second_tenant, "value": "victim", "active": True}
            )
            operations = Operations(MigrationContext.configure(connection))
            with patch.object(migration, "op", operations):
                with self.assertRaises(sa.exc.IntegrityError):
                    with connection.begin_nested():
                        migration.upgrade()
                self.assertEqual(
                    connection.scalar(sa.text(f"SELECT count(*) FROM {table}")), 2
                )
                connection.execute(
                    sa.text(
                        f"UPDATE {table} SET is_active=false WHERE tenant_id=:tenant"
                    ),
                    {"tenant": second_tenant},
                )
                migration.upgrade()
                for statement, params in (
                    (
                        insert,
                        {"tenant": second_tenant, "value": "VICTIM", "active": True},
                    ),
                    (
                        sa.text(
                            f"UPDATE {table} SET is_active=true WHERE tenant_id=:tenant"
                        ),
                        {"tenant": second_tenant},
                    ),
                ):
                    with self.assertRaises(sa.exc.IntegrityError):
                        with connection.begin_nested():
                            connection.execute(statement, params)
                connection.execute(
                    insert, {"tenant": second_tenant, "value": "Other", "active": True}
                )
                with self.assertRaises(sa.exc.IntegrityError):
                    with connection.begin_nested():
                        connection.execute(
                            sa.text(
                                f"UPDATE {table} SET identifier_value='victim' "
                                "WHERE identifier_value='other'"
                            )
                        )
                # Downgrade restores the exact tenant-local uniqueness scope.
                migration.downgrade()
                connection.execute(
                    sa.text(
                        f"UPDATE {table} SET is_active=true "
                        "WHERE identifier_value='victim'"
                    )
                )
                self.assertEqual(
                    connection.scalar(
                        sa.text(f"SELECT count(*) FROM {table} WHERE is_active")
                    ),
                    3,
                )
