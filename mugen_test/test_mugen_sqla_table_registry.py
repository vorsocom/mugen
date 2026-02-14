"""Unit tests for SQLAlchemy table-registry helpers."""

import unittest

from sqlalchemy import Column, Integer, MetaData, String, Table

from mugen.core.gateway.storage.rdbms.sqla import build_table_registry_from_metadata


class TestMugenSQLATableRegistry(unittest.TestCase):
    """Regression tests for SQLAlchemy table-registry helper behavior."""

    def test_build_registry_handles_default_none_exclude(self) -> None:
        """Ensure default `exclude=None` does not raise and keeps tables."""
        metadata = MetaData()
        users_table = Table(
            "users",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("name", String(64), nullable=False),
        )

        registry = build_table_registry_from_metadata(metadata)

        self.assertIn("users", registry)
        self.assertIs(registry["users"], users_table)


if __name__ == "__main__":
    unittest.main()
