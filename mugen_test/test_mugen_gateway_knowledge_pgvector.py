"""Unit tests for mugen.core.gateway.knowledge.pgvector.PgVectorKnowledgeGateway."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from mugen.core.contract.dto.pgvector.search import PgVectorSearchVendorParams
from mugen.core.contract.gateway.knowledge import KnowledgeGatewayRuntimeError
from mugen.core.gateway.knowledge.pgvector import PgVectorKnowledgeGateway


class _VectorLike:
    def tolist(self) -> list[float]:
        return [0.1, 0.2]


class _FakeMappings:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def all(self) -> list[dict]:
        return self._rows


class _FakeResult:
    def __init__(
        self,
        *,
        scalar: object = None,
        rows: list[dict] | None = None,
    ) -> None:
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class _FakeConnection:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.calls: list[tuple[object, dict]] = []

    async def execute(self, statement, params):  # noqa: ANN001
        self.calls.append((statement, params))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeConnectionCtx:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self._connection

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def connect(self) -> _FakeConnectionCtx:
        return _FakeConnectionCtx(self._connection)


def _make_config(
    *,
    search_schema: object = "mugen",
    search_table: object = "downstream_kp_search_doc",
    search_metric: object = "cosine",
    default_top_k: object = 10,
    max_top_k: object = 50,
    snippet_max_chars: object = 240,
    timeout_seconds: object = 2.5,
    max_retries: object = 0,
    retry_backoff_seconds: object = 0.0,
    encoder_model: object = "all-mpnet-base-v2",
    encoder_max_concurrency: object = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        rdbms=SimpleNamespace(
            migration_tracks=SimpleNamespace(core=SimpleNamespace(schema="mugen")),
            sqlalchemy=SimpleNamespace(
                url="postgresql+psycopg://user:password@localhost/mugen",
                pool_pre_ping=True,
                pool_recycle_seconds=1800,
                pool_timeout_seconds=30,
                pool_size=10,
                max_overflow=20,
                statement_timeout_ms=15000,
            ),
        ),
        pgvector=SimpleNamespace(
            search=SimpleNamespace(
                schema=search_schema,
                table=search_table,
                metric=search_metric,
                default_top_k=default_top_k,
                max_top_k=max_top_k,
                snippet_max_chars=snippet_max_chars,
            ),
            api=SimpleNamespace(
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            ),
            encoder=SimpleNamespace(
                model=encoder_model,
                max_concurrency=encoder_max_concurrency,
            ),
        ),
        transformers=SimpleNamespace(
            hf=SimpleNamespace(home="/tmp/hf"),
        ),
    )


def _build_gateway(
    *,
    config: SimpleNamespace,
    logging_gateway: Mock | None = None,
    fake_runtime: SimpleNamespace | None = None,
) -> tuple[PgVectorKnowledgeGateway, SimpleNamespace, Mock]:
    logger = logging_gateway or Mock()
    runtime = fake_runtime or SimpleNamespace(
        engine=SimpleNamespace(),
        aclose=AsyncMock(return_value=None),
    )
    with (
        patch(
            "mugen.core.gateway.knowledge.pgvector.SharedSQLAlchemyRuntime.from_config",
            return_value=runtime,
        ),
        patch("mugen.core.gateway.knowledge.pgvector.SentenceTransformer"),
    ):
        gateway = PgVectorKnowledgeGateway(config, logger)
    return gateway, runtime, logger


class TestMugenGatewayKnowledgePgVector(unittest.IsolatedAsyncioTestCase):
    """Coverage for pgvector knowledge gateway parsing, readiness, and search."""

    def test_config_defaults_and_validation(self) -> None:
        default_config = _make_config(
            search_schema=None,
            default_top_k=None,
            max_top_k=None,
            snippet_max_chars=None,
            timeout_seconds=None,
            encoder_model="   ",
            encoder_max_concurrency=0,
        )
        gateway, _, _ = _build_gateway(config=default_config)

        self.assertEqual(gateway._search_schema, "mugen")  # pylint: disable=protected-access
        self.assertEqual(gateway._search_metric, "cosine")  # pylint: disable=protected-access
        self.assertEqual(gateway._search_default_top_k, 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._search_max_top_k, 50)  # pylint: disable=protected-access
        self.assertEqual(gateway._snippet_max_chars, 240)  # pylint: disable=protected-access
        self.assertEqual(
            gateway._encoder_model_name,  # pylint: disable=protected-access
            "all-mpnet-base-v2",
        )
        self.assertEqual(gateway._encoder_max_concurrency, 4)  # pylint: disable=protected-access
        self.assertIsNone(gateway._api_timeout_seconds)  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "pgvector.search.table is required"):
            _build_gateway(config=_make_config(search_table=" "))

        with self.assertRaisesRegex(RuntimeError, "pgvector.search.metric"):
            _build_gateway(config=_make_config(search_metric="l2"))

        with self.assertRaisesRegex(RuntimeError, "pgvector.search.default_top_k"):
            _build_gateway(config=_make_config(default_top_k=0))

    def test_constructor_warns_and_parser_helpers_cover_edges(self) -> None:
        logger = Mock()
        gateway, _, _ = _build_gateway(
            config=_make_config(
                search_metric=123,
                default_top_k=20,
                max_top_k=10,
                encoder_model=123,
                encoder_max_concurrency="bad",
                max_retries="bad",
            ),
            logging_gateway=logger,
        )
        self.assertEqual(gateway._search_metric, "cosine")  # pylint: disable=protected-access
        self.assertEqual(gateway._search_default_top_k, 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._encoder_model_name, "all-mpnet-base-v2")  # pylint: disable=protected-access
        self.assertEqual(gateway._encoder_max_concurrency, 4)  # pylint: disable=protected-access
        self.assertIsNone(gateway._section("pgvector", "missing"))  # pylint: disable=protected-access

        negative_retry_logger = Mock()
        _build_gateway(
            config=_make_config(max_retries=-1),
            logging_gateway=negative_retry_logger,
        )
        warnings = [str(call.args[0]) for call in negative_retry_logger.warning.call_args_list]
        self.assertIn(
            "PgVectorKnowledgeGateway: max_retries must be non-negative.",
            warnings,
        )

        with self.assertRaisesRegex(RuntimeError, "must be a positive integer"):
            PgVectorKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                True,
                field_name="field",
                default=1,
            )
        with self.assertRaisesRegex(RuntimeError, "must be a positive integer"):
            PgVectorKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                object(),
                field_name="field",
                default=1,
            )
        with self.assertRaisesRegex(RuntimeError, "greater than 0"):
            PgVectorKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                0,
                field_name="field",
                default=1,
            )

    def test_validation_helpers_cover_input_branches(self) -> None:
        self.assertEqual(
            PgVectorKnowledgeGateway._normalize_optional_filter("  value  "),  # pylint: disable=protected-access
            "value",
        )
        self.assertIsNone(
            PgVectorKnowledgeGateway._normalize_optional_filter("   ")  # pylint: disable=protected-access
        )
        self.assertIsNone(
            PgVectorKnowledgeGateway._normalize_optional_filter(123)  # pylint: disable=protected-access
        )

        with self.assertRaisesRegex(ValueError, "search_term must be a string"):
            PgVectorKnowledgeGateway._normalize_search_term(1)  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "search_term must be non-empty"):
            PgVectorKnowledgeGateway._normalize_search_term("   ")  # pylint: disable=protected-access

        self.assertIsNotNone(
            PgVectorKnowledgeGateway._normalize_tenant_id(str(uuid.uuid4()))  # pylint: disable=protected-access
        )
        with self.assertRaisesRegex(ValueError, "tenant_id must be a UUID"):
            PgVectorKnowledgeGateway._normalize_tenant_id(1)  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            PgVectorKnowledgeGateway._normalize_tenant_id("not-a-uuid")  # pylint: disable=protected-access

        self.assertIsNone(
            PgVectorKnowledgeGateway._normalize_min_similarity(None)  # pylint: disable=protected-access
        )
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            PgVectorKnowledgeGateway._normalize_min_similarity("bad")  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            PgVectorKnowledgeGateway._normalize_min_similarity(float("inf"))  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            PgVectorKnowledgeGateway._normalize_min_similarity(2.0)  # pylint: disable=protected-access

    async def test_check_readiness_fails_on_missing_prerequisites(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config())

        gateway._check_database_connectivity = AsyncMock(return_value=None)  # pylint: disable=protected-access
        gateway._check_vector_extension_enabled = AsyncMock(return_value=False)  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "extension 'vector'"):
            await gateway.check_readiness()

        gateway._check_vector_extension_enabled = AsyncMock(return_value=True)  # pylint: disable=protected-access
        gateway._check_projection_table_exists = AsyncMock(return_value=False)  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "configured table was not found"):
            await gateway.check_readiness()

        gateway._check_projection_table_exists = AsyncMock(return_value=True)  # pylint: disable=protected-access
        gateway._fetch_projection_columns = AsyncMock(  # pylint: disable=protected-access
            return_value={"tenant_id": "uuid", "embedding": "vector"}
        )
        with self.assertRaisesRegex(RuntimeError, "missing required column"):
            await gateway.check_readiness()

        gateway._fetch_projection_columns = AsyncMock(  # pylint: disable=protected-access
            return_value={
                "tenant_id": "uuid",
                "knowledge_entry_revision_id": "uuid",
                "knowledge_pack_version_id": "uuid",
                "channel": "citext",
                "locale": "citext",
                "category": "citext",
                "title": "text",
                "body": "text",
                "embedding": "text",
            }
        )
        with self.assertRaisesRegex(RuntimeError, "embedding column must use vector type"):
            await gateway.check_readiness()

        gateway._fetch_projection_columns = AsyncMock(  # pylint: disable=protected-access
            return_value={
                "tenant_id": "uuid",
                "knowledge_entry_revision_id": "uuid",
                "knowledge_pack_version_id": "uuid",
                "channel": "citext",
                "locale": "citext",
                "category": "citext",
                "title": "text",
                "body": "text",
                "embedding": "vector",
            }
        )
        gateway._has_embedding_vector_index = AsyncMock(return_value=False)  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "ivfflat or hnsw index"):
            await gateway.check_readiness()

    async def test_check_readiness_success_path(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config())
        gateway._check_database_connectivity = AsyncMock(return_value=None)  # pylint: disable=protected-access
        gateway._check_vector_extension_enabled = AsyncMock(return_value=True)  # pylint: disable=protected-access
        gateway._check_projection_table_exists = AsyncMock(return_value=True)  # pylint: disable=protected-access
        gateway._fetch_projection_columns = AsyncMock(  # pylint: disable=protected-access
            return_value={
                "tenant_id": "uuid",
                "knowledge_entry_revision_id": "uuid",
                "knowledge_pack_version_id": "uuid",
                "channel": "citext",
                "locale": "citext",
                "category": "citext",
                "title": "text",
                "body": "text",
                "embedding": "vector",
            }
        )
        gateway._has_embedding_vector_index = AsyncMock(return_value=True)  # pylint: disable=protected-access
        gateway._get_encoder = AsyncMock(return_value=object())  # pylint: disable=protected-access

        await gateway.check_readiness()
        gateway._get_encoder.assert_awaited_once_with()  # pylint: disable=protected-access

    async def test_encoder_build_get_and_encode_branches(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config())
        with patch("mugen.core.gateway.knowledge.pgvector.SentenceTransformer") as transformer:
            built = gateway._build_encoder()  # pylint: disable=protected-access
            self.assertIs(built, transformer.return_value)

        sentinel_encoder = object()
        gateway._encoder = sentinel_encoder  # pylint: disable=protected-access
        self.assertIs(await gateway._get_encoder(), sentinel_encoder)  # pylint: disable=protected-access

        gateway._encoder = None  # pylint: disable=protected-access
        with (
            patch.object(gateway, "_build_encoder", return_value=sentinel_encoder),
            patch(
                "mugen.core.gateway.knowledge.pgvector.asyncio.to_thread",
                new=AsyncMock(side_effect=lambda func, *args: func(*args)),
            ),
        ):
            first = await gateway._get_encoder()  # pylint: disable=protected-access
            second = await gateway._get_encoder()  # pylint: disable=protected-access
        self.assertIs(first, sentinel_encoder)
        self.assertIs(second, sentinel_encoder)

        gateway._encoder = SimpleNamespace(encode=lambda _value: _VectorLike())  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term("hello"),  # pylint: disable=protected-access
            [0.1, 0.2],
        )
        gateway._encoder = SimpleNamespace(encode=lambda _value: [1, 2])  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term("hello"),  # pylint: disable=protected-access
            [1.0, 2.0],
        )
        gateway._encoder = SimpleNamespace(encode=lambda _value: (3, 4))  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term("hello"),  # pylint: disable=protected-access
            [3.0, 4.0],
        )

        self.assertEqual(
            PgVectorKnowledgeGateway._vector_literal([1.0, 2.0]),  # pylint: disable=protected-access
            "[1.0,2.0]",
        )
        with self.assertRaisesRegex(RuntimeError, "vector is empty"):
            PgVectorKnowledgeGateway._vector_literal([])  # pylint: disable=protected-access

    async def test_get_encoder_handles_encoder_injected_inside_lock(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config())
        gateway._encoder = None  # pylint: disable=protected-access
        sentinel = object()

        class _InjectingLock:
            async def __aenter__(self_inner):  # noqa: ANN001
                gateway._encoder = sentinel  # pylint: disable=protected-access
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001
                return False

        gateway._encoder_lock = _InjectingLock()  # pylint: disable=protected-access
        resolved = await gateway._get_encoder()  # pylint: disable=protected-access
        self.assertIs(resolved, sentinel)

    async def test_timeout_and_db_fetch_helpers(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config())

        async def _ready():
            return "ok"

        self.assertEqual(
            await PgVectorKnowledgeGateway._await_with_timeout(  # pylint: disable=protected-access
                _ready(),
                timeout_seconds=None,
            ),
            "ok",
        )
        async def _wait_for(awaitable, timeout):  # noqa: ANN001
            _ = timeout
            return await awaitable

        with patch(
            "mugen.core.gateway.knowledge.pgvector.asyncio.wait_for",
            new=AsyncMock(side_effect=_wait_for),
        ) as wait_for:
            self.assertEqual(
                await PgVectorKnowledgeGateway._await_with_timeout(  # pylint: disable=protected-access
                    _ready(),
                    timeout_seconds=1.0,
                ),
                "ok",
            )
            wait_for.assert_awaited_once()

        connection = _FakeConnection(
            responses=[
                _FakeResult(scalar=1),
                _FakeResult(rows=[{"column_name": "tenant_id", "udt_name": "uuid"}]),
            ]
        )
        gateway._engine = _FakeEngine(connection)  # pylint: disable=protected-access

        scalar = await gateway._fetch_scalar("SELECT 1")  # pylint: disable=protected-access
        self.assertEqual(scalar, 1)

        rows = await gateway._fetch_mappings("SELECT column_name FROM x")  # pylint: disable=protected-access
        self.assertEqual(rows, [{"column_name": "tenant_id", "udt_name": "uuid"}])

    async def test_readiness_internal_helpers(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config())
        gateway._fetch_scalar = AsyncMock(return_value=1)  # pylint: disable=protected-access
        await gateway._check_database_connectivity(timeout_seconds=1.0)  # pylint: disable=protected-access

        gateway._fetch_scalar = AsyncMock(return_value=0)  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "connectivity check failed"):
            await gateway._check_database_connectivity(timeout_seconds=1.0)  # pylint: disable=protected-access

        gateway._fetch_scalar = AsyncMock(return_value=True)  # pylint: disable=protected-access
        self.assertTrue(
            await gateway._check_vector_extension_enabled(timeout_seconds=1.0)  # pylint: disable=protected-access
        )

        gateway._fetch_scalar = AsyncMock(return_value=None)  # pylint: disable=protected-access
        self.assertFalse(
            await gateway._check_projection_table_exists(timeout_seconds=1.0)  # pylint: disable=protected-access
        )
        gateway._fetch_scalar = AsyncMock(return_value="mugen.table")  # pylint: disable=protected-access
        self.assertTrue(
            await gateway._check_projection_table_exists(timeout_seconds=1.0)  # pylint: disable=protected-access
        )

        gateway._fetch_mappings = AsyncMock(  # pylint: disable=protected-access
            return_value=[{"column_name": "embedding", "udt_name": None}]
        )
        self.assertEqual(
            await gateway._fetch_projection_columns(timeout_seconds=1.0),  # pylint: disable=protected-access
            {"embedding": ""},
        )

        gateway._fetch_scalar = AsyncMock(return_value=True)  # pylint: disable=protected-access
        self.assertTrue(
            await gateway._has_embedding_vector_index(timeout_seconds=1.0)  # pylint: disable=protected-access
        )

    async def test_check_readiness_default_timeout_and_encoder_failure(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config(timeout_seconds=None))
        gateway._check_database_connectivity = AsyncMock(return_value=None)  # pylint: disable=protected-access
        gateway._check_vector_extension_enabled = AsyncMock(return_value=True)  # pylint: disable=protected-access
        gateway._check_projection_table_exists = AsyncMock(return_value=True)  # pylint: disable=protected-access
        gateway._fetch_projection_columns = AsyncMock(  # pylint: disable=protected-access
            return_value={
                "tenant_id": "uuid",
                "knowledge_entry_revision_id": "uuid",
                "knowledge_pack_version_id": "uuid",
                "channel": "citext",
                "locale": "citext",
                "category": "citext",
                "title": "text",
                "body": "text",
                "embedding": "vector",
            }
        )
        gateway._has_embedding_vector_index = AsyncMock(return_value=True)  # pylint: disable=protected-access
        gateway._get_encoder = AsyncMock(side_effect=RuntimeError("boom"))  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "encoder initialization failed"):
            await gateway.check_readiness()
        gateway._check_database_connectivity.assert_awaited_once_with(timeout_seconds=5.0)  # pylint: disable=protected-access

    async def test_search_query_build_and_fetch_row_helpers(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config())
        statement, params = gateway._build_search_query(  # pylint: disable=protected-access
            query_vector="[0.1,0.2]",
            tenant_id=str(uuid.uuid4()),
            channel="web",
            locale="en-US",
            category="policy",
            top_k=5,
            min_similarity=0.8,
        )
        self.assertIn("tenant_id = CAST(:tenant_id AS uuid)", statement)
        self.assertIn("channel = :channel", statement)
        self.assertIn("locale = :locale", statement)
        self.assertIn("category = :category", statement)
        self.assertIn("min_similarity", statement)
        self.assertEqual(params["top_k"], 5)
        self.assertEqual(params["min_similarity"], 0.8)

        gateway._fetch_mappings = AsyncMock(return_value=[{"id": 1}])  # pylint: disable=protected-access
        rows = await gateway._fetch_search_rows(  # pylint: disable=protected-access
            query_vector="[0.1,0.2]",
            tenant_id=str(uuid.uuid4()),
            channel=None,
            locale=None,
            category=None,
            top_k=2,
            min_similarity=None,
        )
        self.assertEqual(rows, [{"id": 1}])

    def test_item_normalization_helpers(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config())
        self.assertEqual(gateway._resolve_effective_top_k(None), 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_effective_top_k("bad"), 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_effective_top_k(0), 1)  # pylint: disable=protected-access

        self.assertIsNone(gateway._coerce_float(None))  # pylint: disable=protected-access
        self.assertIsNone(gateway._coerce_float("bad"))  # pylint: disable=protected-access
        self.assertIsNone(gateway._coerce_optional_string(None))  # pylint: disable=protected-access
        self.assertEqual(gateway._coerce_optional_string(123), "123")  # pylint: disable=protected-access
        self.assertIsNone(gateway._build_snippet(title=None, body=None))  # pylint: disable=protected-access
        self.assertEqual(
            gateway._build_snippet(title="short", body=None),  # pylint: disable=protected-access
            "short",
        )
        self.assertIsNone(gateway._uuid_text(None))  # pylint: disable=protected-access
        self.assertEqual(gateway._uuid_text("x"), "x")  # pylint: disable=protected-access
        self.assertEqual(gateway._uuid_text(123), "123")  # pylint: disable=protected-access

        row = {
            "tenant_id": uuid.uuid4(),
            "knowledge_entry_revision_id": uuid.uuid4(),
            "knowledge_pack_version_id": uuid.uuid4(),
            "channel": None,
            "locale": None,
            "category": None,
            "title": None,
            "body": None,
            "distance": None,
        }
        normalized = gateway._normalise_item(row)  # pylint: disable=protected-access
        self.assertIsNone(normalized["distance"])
        self.assertIsNone(normalized["similarity"])
        self.assertIsNone(normalized["snippet"])

    async def test_search_applies_scope_filters_and_clamps_top_k(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config(max_top_k=5))
        tenant_id = uuid.uuid4()
        gateway._encode_search_term = AsyncMock(return_value=[0.1, 0.2])  # pylint: disable=protected-access
        gateway._fetch_search_rows = AsyncMock(return_value=[])  # pylint: disable=protected-access

        result = await gateway.search(
            PgVectorSearchVendorParams(
                search_term="billing window",
                tenant_id=tenant_id,
                top_k=99,
                min_similarity=0.8,
                channel="whatsapp",
                locale="en-US",
                category="billing-policy",
            )
        )

        self.assertEqual(result.items, [])
        call_kwargs = gateway._fetch_search_rows.await_args.kwargs  # pylint: disable=protected-access
        self.assertEqual(call_kwargs["tenant_id"], str(tenant_id))
        self.assertEqual(call_kwargs["top_k"], 5)
        self.assertEqual(call_kwargs["channel"], "whatsapp")
        self.assertEqual(call_kwargs["locale"], "en-US")
        self.assertEqual(call_kwargs["category"], "billing-policy")
        self.assertEqual(call_kwargs["min_similarity"], 0.8)

    async def test_search_normalizes_items_and_snippets(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config(snippet_max_chars=8))
        tenant_id = uuid.uuid4()
        revision_id = uuid.uuid4()
        version_id = uuid.uuid4()
        gateway._encode_search_term = AsyncMock(return_value=[0.5, 0.3])  # pylint: disable=protected-access
        gateway._fetch_search_rows = AsyncMock(  # pylint: disable=protected-access
            return_value=[
                {
                    "tenant_id": tenant_id,
                    "knowledge_entry_revision_id": revision_id,
                    "knowledge_pack_version_id": version_id,
                    "channel": "web",
                    "locale": "en-US",
                    "category": "policy",
                    "title": "Title A",
                    "body": "This is long body text.",
                    "distance": 0.25,
                }
            ]
        )

        result = await gateway.search(
            PgVectorSearchVendorParams(
                search_term="refund policy",
                tenant_id=tenant_id,
                top_k=1,
            )
        )

        self.assertEqual(len(result.items), 1)
        first = result.items[0]
        self.assertEqual(first["tenant_id"], str(tenant_id))
        self.assertEqual(first["knowledge_entry_revision_id"], str(revision_id))
        self.assertEqual(first["knowledge_pack_version_id"], str(version_id))
        self.assertEqual(first["snippet"], "This is ")
        self.assertAlmostEqual(first["distance"], 0.25)
        self.assertAlmostEqual(first["similarity"], 0.75)
        self.assertEqual(result.raw_vendor["provider"], "pgvector")
        self.assertEqual(result.raw_vendor["result_count"], 1)

    async def test_search_wraps_timeout_as_runtime_error(self) -> None:
        gateway, _, _ = _build_gateway(config=_make_config())
        gateway._encode_search_term = AsyncMock(return_value=[0.1, 0.2])  # pylint: disable=protected-access
        gateway._fetch_search_rows = AsyncMock(side_effect=asyncio.TimeoutError())  # pylint: disable=protected-access

        with self.assertRaises(KnowledgeGatewayRuntimeError) as raised:
            await gateway.search(
                PgVectorSearchVendorParams(
                    search_term="refund policy",
                    tenant_id=uuid.uuid4(),
                )
            )
        self.assertEqual(raised.exception.provider, "pgvector")
        self.assertEqual(raised.exception.operation, "search")
        self.assertIsInstance(raised.exception.cause, asyncio.TimeoutError)

    async def test_execute_with_retry_and_aclose_paths(self) -> None:
        gateway, runtime, _, = _build_gateway(
            config=_make_config(max_retries=2, retry_backoff_seconds=0.0)
        )
        request = AsyncMock(side_effect=[asyncio.TimeoutError(), "ok"])
        result = await gateway._execute_with_retry(  # pylint: disable=protected-access
            operation="search",
            request_factory=request,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(request.await_count, 2)

        failing = AsyncMock(side_effect=ValueError("bad"))
        with self.assertRaises(ValueError):
            await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=failing,
            )

        await gateway.aclose()
        await gateway.aclose()
        runtime.aclose.assert_awaited_once_with()

        with self.assertRaisesRegex(RuntimeError, "is closed"):
            await gateway.search(
                PgVectorSearchVendorParams(
                    search_term="x",
                    tenant_id=uuid.uuid4(),
                )
            )

    async def test_execute_with_retry_sleep_and_defensive_zero_attempt_window(self) -> None:
        gateway, _, _ = _build_gateway(
            config=_make_config(max_retries=2, retry_backoff_seconds=0.1)
        )
        request = AsyncMock(side_effect=[asyncio.TimeoutError(), "ok"])
        with patch(
            "mugen.core.gateway.knowledge.pgvector.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            result = await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=request,
            )
        self.assertEqual(result, "ok")
        sleep.assert_awaited_once_with(0.1)

        no_attempt_request = AsyncMock()
        with patch("builtins.max", return_value=-1):
            result = await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=no_attempt_request,
            )
        self.assertIsNone(result)
        no_attempt_request.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
