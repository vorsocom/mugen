"""Unit tests for web-runtime SQL helper wrappers."""

import unittest

from sqlalchemy.sql.elements import TextClause

from mugen.core.gateway.storage.web_runtime.sql import text


class TestMugenGatewayStorageWebRuntimeSql(unittest.TestCase):
    """Ensures helper delegates to SQLAlchemy text clause creation."""

    def test_text_returns_text_clause(self) -> None:
        clause = text("SELECT 1")
        self.assertIsInstance(clause, TextClause)
        self.assertEqual(str(clause), "SELECT 1")
