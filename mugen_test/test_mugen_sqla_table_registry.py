"""Unit tests for SQLAlchemy table-registry helpers."""

import unittest
from types import SimpleNamespace

from sqlalchemy import Column, Integer, MetaData, String, Table

from mugen.core.gateway.storage.rdbms.sqla import (
    build_table_registry_from_base,
    build_table_registry_from_metadata,
)


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

    def test_build_registry_include_and_exclude_filters(self) -> None:
        metadata = MetaData()
        users_table = Table(
            "users",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("name", String(64), nullable=False),
        )
        orders_table = Table(
            "orders",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("user_id", Integer, nullable=False),
        )

        only_users = build_table_registry_from_metadata(
            metadata,
            include={"users"},
        )
        self.assertEqual(set(only_users.keys()), {"users"})
        self.assertIs(only_users["users"], users_table)

        without_orders = build_table_registry_from_metadata(
            metadata,
            exclude={"orders"},
        )
        self.assertEqual(set(without_orders.keys()), {"users"})
        self.assertIs(without_orders["users"], users_table)
        self.assertNotIn("orders", without_orders)
        self.assertIsNotNone(orders_table)

    def test_build_registry_from_base_wrapper(self) -> None:
        metadata = MetaData()
        widgets_table = Table(
            "widgets",
            metadata,
            Column("id", Integer, primary_key=True),
        )
        base = SimpleNamespace(metadata=metadata)

        registry = build_table_registry_from_base(base, include={"widgets"})
        self.assertEqual(set(registry.keys()), {"widgets"})
        self.assertIs(registry["widgets"], widgets_table)


if __name__ == "__main__":
    unittest.main()
