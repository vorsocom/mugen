"""Unit tests for mugen.core.gateway.knowledge.chromadb.ChromaKnowledgeGateway."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from mugen.core.contract.dto.chromadb.search import ChromaSearchVendorParams
from mugen.core.contract.gateway.knowledge import KnowledgeGatewayRuntimeError
from mugen.core.gateway.knowledge.chromadb import ChromaKnowledgeGateway


class _VectorLike:
    def tolist(self) -> list[float]:
        return [0.1, 0.2]


def _make_config(
    *,
    host: object = "localhost",
    port: object = 8000,
    ssl: object = False,
    headers: object = None,
    tenant: object = "",
    database: object = "",
    timeout_seconds: object = 2.5,
    max_retries: object = 0,
    retry_backoff_seconds: object = 0.0,
    collection: object = "downstream_kp_search_doc",
    default_top_k: object = 10,
    max_top_k: object = 50,
    snippet_max_chars: object = 240,
    encoder_model: object = "all-mpnet-base-v2",
    encoder_max_concurrency: object = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        chromadb=SimpleNamespace(
            api=SimpleNamespace(
                host=host,
                port=port,
                ssl=ssl,
                headers=headers,
                tenant=tenant,
                database=database,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            ),
            search=SimpleNamespace(
                collection=collection,
                default_top_k=default_top_k,
                max_top_k=max_top_k,
                snippet_max_chars=snippet_max_chars,
            ),
            encoder=SimpleNamespace(
                model=encoder_model,
                max_concurrency=encoder_max_concurrency,
            ),
        ),
        transformers=SimpleNamespace(hf=SimpleNamespace(home="/tmp/hf")),
    )


def _build_gateway(
    *,
    config: SimpleNamespace,
    logging_gateway: Mock | None = None,
) -> tuple[ChromaKnowledgeGateway, Mock]:
    logger = logging_gateway or Mock()
    with patch("mugen.core.gateway.knowledge.chromadb.SentenceTransformer"):
        gateway = ChromaKnowledgeGateway(config, logger)
    return gateway, logger


class TestMugenGatewayKnowledgeChromaDB(unittest.IsolatedAsyncioTestCase):
    """Coverage for ChromaDB knowledge gateway parsing, readiness, and search."""

    def test_config_defaults_and_validation(self) -> None:
        gateway, _ = _build_gateway(
            config=_make_config(
                host=None,
                port=None,
                ssl="on",
                headers=None,
                tenant=123,
                database=123,
                timeout_seconds=None,
                max_retries=1,
                retry_backoff_seconds=0.25,
                default_top_k=None,
                max_top_k=None,
                snippet_max_chars=None,
                encoder_model=123,
                encoder_max_concurrency=0,
            )
        )
        self.assertEqual(gateway._api_host, "")  # pylint: disable=protected-access
        self.assertEqual(gateway._api_port, 8000)  # pylint: disable=protected-access
        self.assertTrue(gateway._api_ssl)  # pylint: disable=protected-access
        self.assertEqual(gateway._api_headers, {})  # pylint: disable=protected-access
        self.assertIsNone(gateway._api_tenant)  # pylint: disable=protected-access
        self.assertIsNone(gateway._api_database)  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._api_timeout_seconds
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._search_default_top_k, 10
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._search_max_top_k, 50
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._snippet_max_chars, 240
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._encoder_model_name, "all-mpnet-base-v2"
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._encoder_max_concurrency, 4
        )  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._section("chromadb", "missing")
        )  # pylint: disable=protected-access

        with self.assertRaisesRegex(
            RuntimeError, "chromadb.search.collection is required"
        ):
            _build_gateway(config=_make_config(collection="   "))

        with self.assertRaisesRegex(RuntimeError, "chromadb.api.port"):
            _build_gateway(config=_make_config(port=0))

        with self.assertRaisesRegex(RuntimeError, "chromadb.search.default_top_k"):
            _build_gateway(config=_make_config(default_top_k=True))

        with self.assertRaisesRegex(RuntimeError, "chromadb.search.max_top_k"):
            _build_gateway(config=_make_config(max_top_k=0))

        with self.assertRaisesRegex(RuntimeError, "chromadb.search.snippet_max_chars"):
            _build_gateway(config=_make_config(snippet_max_chars=0))

        with self.assertRaisesRegex(
            RuntimeError, "chromadb.api.headers must be a table"
        ):
            _build_gateway(config=_make_config(headers=[]))

        with self.assertRaisesRegex(
            RuntimeError, "headers keys must be non-empty strings"
        ):
            _build_gateway(config=_make_config(headers={"   ": "x"}))

        with self.assertRaisesRegex(RuntimeError, "headers values must be strings"):
            _build_gateway(config=_make_config(headers={"x": 1}))

        with self.assertRaisesRegex(RuntimeError, "chromadb.api.timeout_seconds"):
            _build_gateway(config=_make_config(timeout_seconds=0))

        with self.assertRaisesRegex(RuntimeError, "chromadb.api.retry_backoff_seconds"):
            _build_gateway(config=_make_config(retry_backoff_seconds=-1))

    def test_constructor_warnings_and_parse_helpers(self) -> None:
        logger = Mock()
        gateway, _ = _build_gateway(
            config=_make_config(
                default_top_k=20,
                max_top_k=10,
                max_retries="bad",
                retry_backoff_seconds=0.0,
                encoder_max_concurrency="bad",
            ),
            logging_gateway=logger,
        )
        warnings = [str(call.args[0]) for call in logger.warning.call_args_list]
        self.assertIn(
            "ChromaKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k.",
            warnings,
        )
        self.assertIn(
            "ChromaKnowledgeGateway: Invalid max_retries configuration.", warnings
        )

        blank_model_gateway, _ = _build_gateway(
            config=_make_config(encoder_model="   ")
        )
        self.assertEqual(
            blank_model_gateway._encoder_model_name,  # pylint: disable=protected-access
            "all-mpnet-base-v2",
        )

        logger = Mock()
        _build_gateway(config=_make_config(max_retries=-1), logging_gateway=logger)
        warnings = [str(call.args[0]) for call in logger.warning.call_args_list]
        self.assertIn(
            "ChromaKnowledgeGateway: max_retries must be non-negative.", warnings
        )

        self.assertTrue(
            ChromaKnowledgeGateway._parse_bool(
                "true", default=False
            )  # pylint: disable=protected-access
        )
        self.assertFalse(
            ChromaKnowledgeGateway._parse_bool(
                "off", default=True
            )  # pylint: disable=protected-access
        )
        self.assertFalse(
            ChromaKnowledgeGateway._parse_bool(
                "maybe", default=False
            )  # pylint: disable=protected-access
        )
        self.assertTrue(
            ChromaKnowledgeGateway._parse_bool(
                1, default=False
            )  # pylint: disable=protected-access
        )
        self.assertTrue(
            ChromaKnowledgeGateway._parse_bool(
                object(), default=True
            )  # pylint: disable=protected-access
        )
        self.assertFalse(
            ChromaKnowledgeGateway._parse_bool(
                None, default=False
            )  # pylint: disable=protected-access
        )

        with self.assertRaisesRegex(RuntimeError, "must be a positive integer"):
            ChromaKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                object(),
                field_name="field",
                default=1,
            )

        fake_http_client = Mock(return_value=object())
        with patch.dict(
            sys.modules,
            {"chromadb": SimpleNamespace(HttpClient=fake_http_client)},
        ):
            client = ChromaKnowledgeGateway._create_http_client(
                host="local"
            )  # pylint: disable=protected-access
        self.assertIsNotNone(client)
        fake_http_client.assert_called_once_with(host="local")

    async def test_build_and_get_client_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config(host=""))
        with self.assertRaisesRegex(RuntimeError, "requires chromadb.api.host"):
            gateway._build_client()  # pylint: disable=protected-access

        gateway, _ = _build_gateway(
            config=_make_config(
                host="chroma.local",
                port=9000,
                ssl=True,
                headers={"Authorization": "Bearer token"},
                tenant="tenant-a",
                database="db-a",
            )
        )
        with patch.object(
            gateway, "_create_http_client", return_value=object()
        ) as create_client:
            built = gateway._build_client()  # pylint: disable=protected-access
            self.assertIsNotNone(built)
            create_client.assert_called_once()
            kwargs = create_client.call_args.kwargs
            self.assertEqual(kwargs["host"], "chroma.local")
            self.assertEqual(kwargs["port"], 9000)
            self.assertTrue(kwargs["ssl"])
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer token")
            self.assertEqual(kwargs["tenant"], "tenant-a")
            self.assertEqual(kwargs["database"], "db-a")

        gateway, _ = _build_gateway(config=_make_config(host="local", headers=None))
        with patch.object(
            gateway, "_create_http_client", return_value=object()
        ) as create_client:
            gateway._build_client()  # pylint: disable=protected-access
            kwargs = create_client.call_args.kwargs
            self.assertNotIn("headers", kwargs)
            self.assertNotIn("tenant", kwargs)
            self.assertNotIn("database", kwargs)

        sentinel = object()
        gateway._client = sentinel  # pylint: disable=protected-access
        self.assertIs(
            await gateway._get_client(), sentinel
        )  # pylint: disable=protected-access

        gateway._client = None  # pylint: disable=protected-access
        with patch.object(
            gateway, "_build_client", return_value=sentinel
        ) as build_client, patch(
            "mugen.core.gateway.knowledge.chromadb.asyncio.to_thread",
            new=AsyncMock(side_effect=lambda func: func()),
        ) as to_thread:
            first = await gateway._get_client()  # pylint: disable=protected-access
            second = await gateway._get_client()  # pylint: disable=protected-access
        self.assertIs(first, sentinel)
        self.assertIs(second, sentinel)
        build_client.assert_called_once()
        to_thread.assert_awaited_once()

        class _InjectingClientLock:
            async def __aenter__(self_inner):  # noqa: ANN001
                gateway._client = sentinel  # pylint: disable=protected-access
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001
                return False

        gateway._client = None  # pylint: disable=protected-access
        gateway._client_lock = (
            _InjectingClientLock()
        )  # pylint: disable=protected-access
        self.assertIs(
            await gateway._get_client(), sentinel
        )  # pylint: disable=protected-access

    async def test_get_collection_and_encoder_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())
        fake_collection = object()
        fake_client = SimpleNamespace(get_collection=Mock(return_value=fake_collection))
        gateway._client = fake_client  # pylint: disable=protected-access
        first = await gateway._get_collection()  # pylint: disable=protected-access
        second = await gateway._get_collection()  # pylint: disable=protected-access
        self.assertIs(first, fake_collection)
        self.assertIs(second, fake_collection)
        fake_client.get_collection.assert_called_once_with("downstream_kp_search_doc")

        class _InjectingCollectionLock:
            async def __aenter__(self_inner):  # noqa: ANN001
                gateway._collection = (
                    fake_collection  # pylint: disable=protected-access
                )
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001
                return False

        gateway._collection = None  # pylint: disable=protected-access
        gateway._collection_lock = (
            _InjectingCollectionLock()
        )  # pylint: disable=protected-access
        self.assertIs(
            await gateway._get_collection(), fake_collection
        )  # pylint: disable=protected-access

        with patch(
            "mugen.core.gateway.knowledge.chromadb.SentenceTransformer"
        ) as transformer:
            built = gateway._build_encoder()  # pylint: disable=protected-access
            self.assertIs(built, transformer.return_value)

        sentinel_encoder = object()
        gateway._encoder = sentinel_encoder  # pylint: disable=protected-access
        self.assertIs(
            await gateway._get_encoder(), sentinel_encoder
        )  # pylint: disable=protected-access

        gateway._encoder = None  # pylint: disable=protected-access
        with patch.object(
            gateway, "_build_encoder", return_value=sentinel_encoder
        ), patch(
            "mugen.core.gateway.knowledge.chromadb.asyncio.to_thread",
            new=AsyncMock(side_effect=lambda func, *args: func(*args)),
        ):
            self.assertIs(
                await gateway._get_encoder(),  # pylint: disable=protected-access
                sentinel_encoder,
            )

        class _InjectingLock:
            async def __aenter__(self_inner):  # noqa: ANN001
                gateway._encoder = sentinel_encoder  # pylint: disable=protected-access
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001
                return False

        gateway._encoder = None  # pylint: disable=protected-access
        gateway._encoder_lock = _InjectingLock()  # pylint: disable=protected-access
        self.assertIs(
            await gateway._get_encoder(),  # pylint: disable=protected-access
            sentinel_encoder,
        )

        gateway._encoder = SimpleNamespace(
            encode=lambda _term: _VectorLike()
        )  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term(
                "hello"
            ),  # pylint: disable=protected-access
            [0.1, 0.2],
        )
        gateway._encoder = SimpleNamespace(
            encode=lambda _term: [1, 2]
        )  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term(
                "hello"
            ),  # pylint: disable=protected-access
            [1.0, 2.0],
        )
        gateway._encoder = SimpleNamespace(
            encode=lambda _term: (3, 4)
        )  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term(
                "hello"
            ),  # pylint: disable=protected-access
            [3.0, 4.0],
        )

    async def test_readiness_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config(host=""))
        with self.assertRaisesRegex(RuntimeError, "requires chromadb.api.host"):
            await gateway.check_readiness()

        gateway, _ = _build_gateway(config=_make_config(collection="collection-a"))
        gateway._get_collection = AsyncMock(
            side_effect=RuntimeError("boom")
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "collection readiness probe failed"):
            await gateway.check_readiness()

        gateway, _ = _build_gateway(config=_make_config(collection="collection-a"))
        gateway._get_collection = AsyncMock(
            return_value=object()
        )  # pylint: disable=protected-access
        gateway._get_encoder = AsyncMock(
            side_effect=RuntimeError("boom")
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "encoder initialization failed"):
            await gateway.check_readiness()

        gateway, _ = _build_gateway(config=_make_config(timeout_seconds=None))
        gateway._get_collection = AsyncMock(
            return_value=object()
        )  # pylint: disable=protected-access
        gateway._get_encoder = AsyncMock(
            return_value=object()
        )  # pylint: disable=protected-access
        timeout_values: list[float] = []

        async def _wait_for(awaitable, timeout):
            timeout_values.append(float(timeout))
            return await awaitable

        with patch(
            "mugen.core.gateway.knowledge.chromadb.asyncio.wait_for",
            new=AsyncMock(side_effect=_wait_for),
        ):
            await gateway.check_readiness()
        self.assertEqual(timeout_values, [5.0, 5.0])

        gateway, _ = _build_gateway(config=_make_config(collection="collection-a"))
        gateway._search_collection = " "  # pylint: disable=protected-access
        with self.assertRaisesRegex(
            RuntimeError, "requires chromadb.search.collection"
        ):
            await gateway.check_readiness()

    def test_normalization_helpers(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())

        self.assertEqual(
            ChromaKnowledgeGateway._normalize_optional_filter(
                "  value  "
            ),  # pylint: disable=protected-access
            "value",
        )
        self.assertIsNone(
            ChromaKnowledgeGateway._normalize_optional_filter(
                123
            )  # pylint: disable=protected-access
        )
        self.assertIsNone(
            ChromaKnowledgeGateway._normalize_optional_filter(
                "   "
            )  # pylint: disable=protected-access
        )

        with self.assertRaisesRegex(ValueError, "search_term must be a string"):
            ChromaKnowledgeGateway._normalize_search_term(
                1
            )  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "search_term must be non-empty"):
            ChromaKnowledgeGateway._normalize_search_term(
                " "
            )  # pylint: disable=protected-access

        self.assertIsNotNone(
            ChromaKnowledgeGateway._normalize_tenant_id(
                str(uuid.uuid4())
            )  # pylint: disable=protected-access
        )
        with self.assertRaisesRegex(ValueError, "tenant_id must be a UUID"):
            ChromaKnowledgeGateway._normalize_tenant_id(
                123
            )  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            ChromaKnowledgeGateway._normalize_tenant_id(
                "not-a-uuid"
            )  # pylint: disable=protected-access

        self.assertIsNone(
            ChromaKnowledgeGateway._normalize_min_similarity(
                None
            )  # pylint: disable=protected-access
        )
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            ChromaKnowledgeGateway._normalize_min_similarity(
                "bad"
            )  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            ChromaKnowledgeGateway._normalize_min_similarity(
                float("inf")
            )  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            ChromaKnowledgeGateway._normalize_min_similarity(
                2.0
            )  # pylint: disable=protected-access

        self.assertEqual(
            gateway._resolve_effective_top_k(None), 10
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_effective_top_k("bad"), 10
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_effective_top_k(0), 1
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_effective_top_k(200), 50
        )  # pylint: disable=protected-access

        self.assertIsNone(
            gateway._coerce_float(None)
        )  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._coerce_float("bad")
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._coerce_optional_string(123), "123"
        )  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._coerce_optional_string(None)
        )  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._build_snippet(title=None, body=None)
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._build_snippet(
                title="short", body=None
            ),  # pylint: disable=protected-access
            "short",
        )

        valid_id = str(uuid.uuid4())
        self.assertEqual(
            gateway._normalize_uuid_text(
                valid_id, field_name="x"
            ),  # pylint: disable=protected-access
            valid_id,
        )
        self.assertEqual(
            gateway._normalize_uuid_text(
                uuid.UUID(valid_id), field_name="x"
            ),  # pylint: disable=protected-access
            valid_id,
        )
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            gateway._normalize_uuid_text(
                None, field_name="x"
            )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            gateway._normalize_uuid_text(
                "   ", field_name="x"
            )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            gateway._normalize_uuid_text(
                "bad-id", field_name="x"
            )  # pylint: disable=protected-access

        self.assertEqual(
            gateway._extract_nested_list([[1, 2]]),  # pylint: disable=protected-access
            [1, 2],
        )
        self.assertEqual(
            gateway._extract_nested_list([1, 2]),  # pylint: disable=protected-access
            [1, 2],
        )
        self.assertEqual(
            gateway._extract_nested_list(None),  # pylint: disable=protected-access
            [],
        )
        self.assertEqual(
            gateway._extract_nested_list([]),  # pylint: disable=protected-access
            [],
        )

    def test_item_normalization_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config(snippet_max_chars=8))
        with self.assertRaisesRegex(RuntimeError, "metadata item must be a table"):
            gateway._normalise_item(  # pylint: disable=protected-access
                metadata=[],
                document=None,
                distance_raw=0.1,
            )
        with self.assertRaisesRegex(RuntimeError, "missing required key"):
            gateway._normalise_item(  # pylint: disable=protected-access
                metadata={"tenant_id": str(uuid.uuid4())},
                document=None,
                distance_raw=0.1,
            )
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            gateway._normalise_item(  # pylint: disable=protected-access
                metadata={
                    "tenant_id": "bad",
                    "knowledge_entry_revision_id": str(uuid.uuid4()),
                    "knowledge_pack_version_id": str(uuid.uuid4()),
                    "channel": "web",
                    "locale": "en-US",
                    "category": "policy",
                    "title": "Title",
                    "body": "",
                },
                document="doc body",
                distance_raw=0.1,
            )

        metadata = {
            "tenant_id": str(uuid.uuid4()),
            "knowledge_entry_revision_id": str(uuid.uuid4()),
            "knowledge_pack_version_id": str(uuid.uuid4()),
            "channel": "web",
            "locale": "en-US",
            "category": "policy",
            "title": "Title",
            "body": "",
        }
        item = gateway._normalise_item(  # pylint: disable=protected-access
            metadata=metadata,
            document="This is long body.",
            distance_raw="0.25",
        )
        self.assertEqual(item["snippet"], "This is ")
        self.assertAlmostEqual(float(item["distance"]), 0.25)
        self.assertAlmostEqual(float(item["similarity"]), 0.75)

        items = gateway._normalise_items(  # pylint: disable=protected-access
            query_result={
                "metadatas": [[metadata]],
                "documents": [["This is long body."]],
                "distances": [["0.25"]],
            },
            min_similarity=0.8,
        )
        self.assertEqual(items, [])

    async def test_query_collection_and_search_success(self) -> None:
        gateway, _ = _build_gateway(
            config=_make_config(max_top_k=5, snippet_max_chars=12)
        )
        tenant_id = uuid.uuid4()
        revision_id = uuid.uuid4()
        version_id = uuid.uuid4()

        fake_collection = SimpleNamespace(
            query=Mock(
                return_value={
                    "metadatas": [
                        [
                            {
                                "tenant_id": str(tenant_id),
                                "knowledge_entry_revision_id": str(revision_id),
                                "knowledge_pack_version_id": str(version_id),
                                "channel": "whatsapp",
                                "locale": "en-US",
                                "category": "billing",
                                "title": "Refund policy",
                                "body": "Customers can request refunds within 30 days.",
                            }
                        ]
                    ],
                    "documents": [["Doc override"]],
                    "distances": [[0.2]],
                }
            )
        )
        gateway._collection = fake_collection  # pylint: disable=protected-access
        gateway._encode_search_term = AsyncMock(
            return_value=[0.1, 0.2]
        )  # pylint: disable=protected-access

        result = await gateway.search(
            ChromaSearchVendorParams(
                search_term="refund policy",
                tenant_id=tenant_id,
                top_k=99,
                min_similarity=0.5,
                channel="  whatsapp ",
                locale="en-US",
                category="billing",
            )
        )
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.raw_vendor["provider"], "chromadb")
        self.assertEqual(result.raw_vendor["top_k"], 5)
        self.assertEqual(result.raw_vendor["result_count"], 1)
        self.assertEqual(
            result.items[0]["knowledge_entry_revision_id"], str(revision_id)
        )
        self.assertEqual(result.items[0]["knowledge_pack_version_id"], str(version_id))
        self.assertEqual(result.items[0]["tenant_id"], str(tenant_id))
        fake_collection.query.assert_called_once()
        query_kwargs = fake_collection.query.call_args.kwargs
        self.assertEqual(query_kwargs["n_results"], 5)
        self.assertEqual(
            query_kwargs["where"],
            {
                "tenant_id": str(tenant_id),
                "channel": "whatsapp",
                "locale": "en-US",
                "category": "billing",
            },
        )

    async def test_search_and_query_error_wrapping(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())
        gateway._encode_search_term = AsyncMock(
            return_value=[0.1, 0.2]
        )  # pylint: disable=protected-access
        gateway._query_collection = AsyncMock(
            return_value="bad"
        )  # pylint: disable=protected-access
        with self.assertRaises(KnowledgeGatewayRuntimeError) as raised:
            await gateway.search(
                ChromaSearchVendorParams(
                    search_term="x",
                    tenant_id=uuid.uuid4(),
                )
            )
        self.assertEqual(raised.exception.provider, "chromadb")
        self.assertEqual(raised.exception.operation, "search")

        gateway, _ = _build_gateway(config=_make_config())
        gateway._collection = SimpleNamespace(
            query=Mock(return_value="bad")
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "invalid query payload"):
            await gateway._query_collection(  # pylint: disable=protected-access
                query_vector=[0.1],
                tenant_id=str(uuid.uuid4()),
                channel=None,
                locale=None,
                category=None,
                top_k=1,
            )

    async def test_execute_with_retry_and_aclose_paths(self) -> None:
        gateway, logger = _build_gateway(
            config=_make_config(max_retries=2, retry_backoff_seconds=0.1)
        )
        request_factory = AsyncMock(side_effect=[RuntimeError("boom"), "ok"])
        with patch(
            "mugen.core.gateway.knowledge.chromadb.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            result = (
                await gateway._execute_with_retry(  # pylint: disable=protected-access
                    operation="search",
                    request_factory=request_factory,
                )
            )
        self.assertEqual(result, "ok")
        self.assertEqual(request_factory.await_count, 2)
        sleep.assert_awaited_once_with(0.1)
        self.assertTrue(logger.warning.called)

        failing_factory = AsyncMock(side_effect=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=failing_factory,
            )

        gateway._api_max_retries = 1  # pylint: disable=protected-access
        gateway._api_retry_backoff_seconds = 0.0  # pylint: disable=protected-access
        no_sleep_factory = AsyncMock(side_effect=[RuntimeError("boom"), "ok"])
        with patch(
            "mugen.core.gateway.knowledge.chromadb.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            result = (
                await gateway._execute_with_retry(  # pylint: disable=protected-access
                    operation="search",
                    request_factory=no_sleep_factory,
                )
            )
        self.assertEqual(result, "ok")
        sleep.assert_not_awaited()

        with patch("builtins.max", return_value=-1):
            no_attempt = AsyncMock()
            result = (
                await gateway._execute_with_retry(  # pylint: disable=protected-access
                    operation="search",
                    request_factory=no_attempt,
                )
            )
        self.assertIsNone(result)
        no_attempt.assert_not_awaited()

        gateway = ChromaKnowledgeGateway.__new__(ChromaKnowledgeGateway)
        gateway._closed = False  # pylint: disable=protected-access
        close_mock = Mock(return_value=None)
        gateway._client = SimpleNamespace(
            close=close_mock
        )  # pylint: disable=protected-access
        gateway._collection = object()  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())
        close_mock.assert_called_once_with()
        self.assertIsNone(gateway._client)  # pylint: disable=protected-access
        self.assertIsNone(gateway._collection)  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

        gateway = ChromaKnowledgeGateway.__new__(ChromaKnowledgeGateway)
        gateway._closed = False  # pylint: disable=protected-access
        gateway._collection = None  # pylint: disable=protected-access

        async def _async_close():
            return None

        gateway._client = SimpleNamespace(
            close=_async_close
        )  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

        gateway = ChromaKnowledgeGateway.__new__(ChromaKnowledgeGateway)
        gateway._closed = False  # pylint: disable=protected-access
        gateway._client = SimpleNamespace()
        gateway._collection = None  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

        gateway, _ = _build_gateway(config=_make_config())
        gateway._closed = True  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "is closed"):
            gateway._assert_open()  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "is closed"):
            await gateway.search(
                ChromaSearchVendorParams(
                    search_term="x",
                    tenant_id=uuid.uuid4(),
                )
            )


if __name__ == "__main__":
    unittest.main()
