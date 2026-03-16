"""Unit tests for mugen.core.gateway.knowledge.weaviate.WeaviateKnowledgeGateway."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from mugen.core.contract.dto.weaviate.search import WeaviateSearchVendorParams
from mugen.core.contract.gateway.knowledge import KnowledgeGatewayRuntimeError
from mugen.core.gateway.knowledge.weaviate import WeaviateKnowledgeGateway


class _VectorLike:
    def tolist(self) -> list[float]:
        return [0.1, 0.2]


class _IterableVector:
    def __iter__(self):
        return iter([0.3, 0.4])


class _QueryObject:
    def __init__(self, *, properties: object, distance: object) -> None:
        self.properties = properties
        self.metadata = SimpleNamespace(distance=distance)


class _PropertiesWithModelDump:
    def model_dump(self) -> dict[str, object]:
        return {"x": 1}


class _PropertiesWithDict:
    def dict(self) -> dict[str, object]:
        return {"y": 2}


class _PropertiesWithAttrs:
    def __init__(self) -> None:
        self.z = 3


class _LockThatSetsAttr:
    def __init__(self, target: object, attr_name: str, value: object) -> None:
        self._target = target
        self._attr_name = attr_name
        self._value = value

    async def __aenter__(self):
        setattr(self._target, self._attr_name, self._value)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _payload(
    *,
    tenant_id: str | None = None,
    revision_id: str | None = None,
    version_id: str | None = None,
    title: object = "Title",
    body: object = "Body text",
) -> dict[str, object]:
    return {
        "tenant_id": tenant_id or str(uuid.uuid4()),
        "knowledge_entry_revision_id": revision_id or str(uuid.uuid4()),
        "knowledge_pack_version_id": version_id or str(uuid.uuid4()),
        "channel": "web",
        "locale": "en-US",
        "category": "billing",
        "title": title,
        "body": body,
    }


def _make_config(
    *,
    http_host: object = "localhost",
    http_port: object = 8080,
    http_secure: object = False,
    grpc_host: object = "localhost",
    grpc_port: object = 50051,
    grpc_secure: object = False,
    api_key: object = "",
    headers: object = None,
    timeout_seconds: object = 2.5,
    max_retries: object = 0,
    retry_backoff_seconds: object = 0.0,
    collection: object = "DownstreamKPSearchDoc",
    target_vector: object = "",
    default_top_k: object = 10,
    max_top_k: object = 50,
    snippet_max_chars: object = 240,
    encoder_model: object = "all-mpnet-base-v2",
    encoder_max_concurrency: object = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        weaviate=SimpleNamespace(
            api=SimpleNamespace(
                http_host=http_host,
                http_port=http_port,
                http_secure=http_secure,
                grpc_host=grpc_host,
                grpc_port=grpc_port,
                grpc_secure=grpc_secure,
                key=api_key,
                headers=headers,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            ),
            search=SimpleNamespace(
                collection=collection,
                target_vector=target_vector,
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
) -> tuple[WeaviateKnowledgeGateway, Mock]:
    logger = logging_gateway or Mock()
    with patch("mugen.core.gateway.knowledge.weaviate.SentenceTransformer"):
        gateway = WeaviateKnowledgeGateway(config, logger)
    return gateway, logger


class TestMugenGatewayKnowledgeWeaviate(unittest.IsolatedAsyncioTestCase):
    """Coverage for Weaviate knowledge gateway parsing, readiness, and search."""

    def test_config_defaults_and_validation(self) -> None:
        gateway, _ = _build_gateway(
            config=_make_config(
                http_secure="on",
                grpc_secure=1,
                api_key=123,
                headers=None,
                timeout_seconds=None,
                default_top_k=None,
                max_top_k=None,
                snippet_max_chars=None,
                target_vector=None,
                encoder_model=123,
                encoder_max_concurrency=0,
            )
        )
        self.assertEqual(gateway._api_http_host, "localhost")  # pylint: disable=protected-access
        self.assertEqual(gateway._api_http_port, 8080)  # pylint: disable=protected-access
        self.assertTrue(gateway._api_http_secure)  # pylint: disable=protected-access
        self.assertEqual(gateway._api_grpc_host, "localhost")  # pylint: disable=protected-access
        self.assertEqual(gateway._api_grpc_port, 50051)  # pylint: disable=protected-access
        self.assertTrue(gateway._api_grpc_secure)  # pylint: disable=protected-access
        self.assertIsNone(gateway._api_key)  # pylint: disable=protected-access
        self.assertEqual(gateway._api_headers, {})  # pylint: disable=protected-access
        self.assertIsNone(gateway._api_timeout_seconds)  # pylint: disable=protected-access
        self.assertIsNone(gateway._search_target_vector)  # pylint: disable=protected-access
        self.assertEqual(gateway._search_default_top_k, 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._search_max_top_k, 50)  # pylint: disable=protected-access
        self.assertEqual(gateway._snippet_max_chars, 240)  # pylint: disable=protected-access
        self.assertEqual(gateway._encoder_model_name, "all-mpnet-base-v2")  # pylint: disable=protected-access
        self.assertEqual(gateway._encoder_max_concurrency, 4)  # pylint: disable=protected-access
        self.assertIsNone(gateway._section("weaviate", "missing"))  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "weaviate.api.http_host is required"):
            _build_gateway(config=_make_config(http_host="  "))
        with self.assertRaisesRegex(RuntimeError, "weaviate.api.grpc_host is required"):
            _build_gateway(config=_make_config(grpc_host="  "))
        with self.assertRaisesRegex(RuntimeError, "weaviate.search.collection is required"):
            _build_gateway(config=_make_config(collection="  "))
        with self.assertRaisesRegex(RuntimeError, "weaviate.api.http_port"):
            _build_gateway(config=_make_config(http_port=0))
        with self.assertRaisesRegex(RuntimeError, "weaviate.api.grpc_port"):
            _build_gateway(config=_make_config(grpc_port=0))
        with self.assertRaisesRegex(RuntimeError, "weaviate.search.default_top_k"):
            _build_gateway(config=_make_config(default_top_k=True))
        with self.assertRaisesRegex(RuntimeError, "weaviate.search.max_top_k"):
            _build_gateway(config=_make_config(max_top_k=0))
        with self.assertRaisesRegex(RuntimeError, "weaviate.search.snippet_max_chars"):
            _build_gateway(config=_make_config(snippet_max_chars=0))
        with self.assertRaisesRegex(RuntimeError, "weaviate.api.timeout_seconds"):
            _build_gateway(config=_make_config(timeout_seconds=0))
        with self.assertRaisesRegex(RuntimeError, "weaviate.api.retry_backoff_seconds"):
            _build_gateway(config=_make_config(retry_backoff_seconds=-1))
        with self.assertRaisesRegex(RuntimeError, "weaviate.api.headers must be a table"):
            _build_gateway(config=_make_config(headers=[]))
        with self.assertRaisesRegex(RuntimeError, "headers keys must be non-empty strings"):
            _build_gateway(config=_make_config(headers={"   ": "x"}))
        with self.assertRaisesRegex(RuntimeError, "headers values must be strings"):
            _build_gateway(config=_make_config(headers={"x": 1}))

    def test_constructor_warnings_and_parsing_helpers(self) -> None:
        logger = Mock()
        gateway, _ = _build_gateway(
            config=_make_config(
                default_top_k=20,
                max_top_k=10,
                max_retries="bad",
                encoder_max_concurrency="bad",
            ),
            logging_gateway=logger,
        )
        warnings = [str(call.args[0]) for call in logger.warning.call_args_list]
        self.assertIn(
            "WeaviateKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k.",
            warnings,
        )
        self.assertIn(
            "WeaviateKnowledgeGateway: Invalid max_retries configuration.",
            warnings,
        )

        _build_gateway(
            config=_make_config(max_retries=-1),
            logging_gateway=logger,
        )
        warnings = [str(call.args[0]) for call in logger.warning.call_args_list]
        self.assertIn(
            "WeaviateKnowledgeGateway: max_retries must be non-negative.",
            warnings,
        )

        with self.assertRaisesRegex(RuntimeError, "must be a positive integer"):
            WeaviateKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                object(),
                field_name="field",
                default=1,
            )
        with self.assertRaisesRegex(RuntimeError, "must be a positive integer"):
            WeaviateKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                True,
                field_name="field",
                default=1,
            )
        with self.assertRaisesRegex(RuntimeError, "greater than 0"):
            WeaviateKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                0,
                field_name="field",
                default=1,
            )

        gateway._config.weaviate.encoder.model = 123  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_encoder_model_name(),  # pylint: disable=protected-access
            "all-mpnet-base-v2",
        )
        gateway._config.weaviate.encoder.model = "  "  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_encoder_model_name(),  # pylint: disable=protected-access
            "all-mpnet-base-v2",
        )

    def test_additional_helper_coverage_paths(self) -> None:
        gateway, _ = _build_gateway(
            config=_make_config(
                api_key="  secret  ",
                headers={"  x-test-header  ": "value"},
            )
        )
        self.assertEqual(gateway._api_key, "secret")  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            gateway._api_headers,
            {"x-test-header": "value"},
        )

        tenant_uuid = str(uuid.uuid4())
        self.assertEqual(
            WeaviateKnowledgeGateway._normalize_tenant_id(f"  {tenant_uuid}  "),  # pylint: disable=protected-access
            tenant_uuid,
        )
        self.assertIsNone(gateway._build_snippet(title=None, body=None))  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "invalid query payload"):
            WeaviateKnowledgeGateway._extract_query_objects(  # pylint: disable=protected-access
                SimpleNamespace(objects=None)
            )

        class _PropertiesWithNonDictSerializers:
            def __init__(self) -> None:
                self.fallback = "attr"

            def model_dump(self):
                return ["not-a-dict"]

            def dict(self):
                return ("still-not-a-dict",)

        self.assertEqual(
            WeaviateKnowledgeGateway._extract_properties(  # pylint: disable=protected-access
                SimpleNamespace(properties=_PropertiesWithNonDictSerializers())
            ),
            {"fallback": "attr"},
        )

    def test_create_client_uses_imported_weaviate_helpers(self) -> None:
        connect_mock = Mock(return_value=object())

        class _FakeAuth:  # pylint: disable=too-few-public-methods
            @staticmethod
            def api_key(value: str) -> str:
                return f"auth:{value}"

        class _FakeTimeout:  # pylint: disable=too-few-public-methods
            def __init__(self, *, query, init):
                self.query = query
                self.init = init

        class _FakeAdditionalConfig:  # pylint: disable=too-few-public-methods
            def __init__(self, *, timeout):
                self.timeout = timeout

        weaviate_module = ModuleType("weaviate")
        weaviate_module.connect_to_custom = connect_mock
        auth_module = ModuleType("weaviate.auth")
        auth_module.Auth = _FakeAuth
        classes_module = ModuleType("weaviate.classes")
        init_module = ModuleType("weaviate.classes.init")
        init_module.AdditionalConfig = _FakeAdditionalConfig
        init_module.Timeout = _FakeTimeout

        with patch.dict(
            sys.modules,
            {
                "weaviate": weaviate_module,
                "weaviate.auth": auth_module,
                "weaviate.classes": classes_module,
                "weaviate.classes.init": init_module,
            },
        ):
            WeaviateKnowledgeGateway._create_client(  # pylint: disable=protected-access
                http_host="localhost",
                http_port=8080,
                http_secure=False,
                grpc_host="localhost",
                grpc_port=50051,
                grpc_secure=False,
                api_key="secret",
                headers={"x-api-key": "v"},
                timeout_seconds=2.5,
            )

            WeaviateKnowledgeGateway._create_client(  # pylint: disable=protected-access
                http_host="localhost",
                http_port=8080,
                http_secure=False,
                grpc_host="localhost",
                grpc_port=50051,
                grpc_secure=False,
                api_key=None,
                headers={},
                timeout_seconds=None,
            )

        self.assertEqual(connect_mock.call_count, 2)
        kwargs = connect_mock.call_args_list[0].kwargs
        self.assertEqual(kwargs["auth_credentials"], "auth:secret")
        self.assertEqual(kwargs["headers"], {"x-api-key": "v"})
        self.assertEqual(kwargs["additional_config"].timeout.query, 2.5)
        self.assertEqual(kwargs["additional_config"].timeout.init, 2.5)
        self.assertFalse(kwargs["skip_init_checks"])

        kwargs = connect_mock.call_args_list[1].kwargs
        self.assertIsNone(kwargs["auth_credentials"])
        self.assertIsNone(kwargs["headers"])
        self.assertIsNone(kwargs["additional_config"])

    async def test_client_collection_and_encoder_lifecycle(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())

        fake_collection = object()
        fake_client = SimpleNamespace(
            collections=SimpleNamespace(get=Mock(return_value=fake_collection))
        )
        with patch.object(gateway, "_create_client", return_value=fake_client) as create:
            first_client = await gateway._get_client()  # pylint: disable=protected-access
            second_client = await gateway._get_client()  # pylint: disable=protected-access
            self.assertIs(first_client, second_client)
            create.assert_called_once()

        first_collection = await gateway._get_collection()  # pylint: disable=protected-access
        second_collection = await gateway._get_collection()  # pylint: disable=protected-access
        self.assertIs(first_collection, second_collection)
        fake_client.collections.get.assert_called_once_with("DownstreamKPSearchDoc")

        gateway._api_http_host = ""  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "requires weaviate.api.http_host"):
            gateway._build_client()  # pylint: disable=protected-access
        gateway._api_http_host = "localhost"  # pylint: disable=protected-access
        gateway._api_grpc_host = ""  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "requires weaviate.api.grpc_host"):
            gateway._build_client()  # pylint: disable=protected-access

        gateway._api_grpc_host = "localhost"  # pylint: disable=protected-access
        gateway._collection = None  # pylint: disable=protected-access
        gateway._client = SimpleNamespace(collections=SimpleNamespace())  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "collection API is unavailable"):
            await gateway._get_collection()  # pylint: disable=protected-access

    async def test_encoder_build_and_encode_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())

        with patch("mugen.core.gateway.knowledge.weaviate.SentenceTransformer") as transformer:
            built = gateway._build_encoder()  # pylint: disable=protected-access
            self.assertIs(built, transformer.return_value)
            transformer.assert_called_once_with(
                model_name_or_path="all-mpnet-base-v2",
                tokenizer_kwargs={"clean_up_tokenization_spaces": False},
                cache_folder="/tmp/hf",
            )

        built_encoder = object()
        with (
            patch.object(gateway, "_build_encoder", return_value=built_encoder),
            patch(
                "mugen.core.gateway.knowledge.weaviate.asyncio.to_thread",
                new=AsyncMock(return_value=built_encoder),
            ) as to_thread,
        ):
            first = await gateway._get_encoder()  # pylint: disable=protected-access
            second = await gateway._get_encoder()  # pylint: disable=protected-access
            self.assertIs(first, built_encoder)
            self.assertIs(second, built_encoder)
            to_thread.assert_awaited_once()

        gateway._encoder = SimpleNamespace(encode=Mock(return_value=_VectorLike()))  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term("abc"),  # pylint: disable=protected-access
            [0.1, 0.2],
        )
        gateway._encoder = SimpleNamespace(encode=Mock(return_value=[0.3, 0.4]))  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term("abc"),  # pylint: disable=protected-access
            [0.3, 0.4],
        )
        gateway._encoder = SimpleNamespace(encode=Mock(return_value=_IterableVector()))  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._encode_search_term("abc"),  # pylint: disable=protected-access
            [0.3, 0.4],
        )

    async def test_lazy_getters_use_values_injected_during_lock(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())

        cached_client = object()
        gateway._client = None  # pylint: disable=protected-access
        gateway._client_lock = _LockThatSetsAttr(  # pylint: disable=protected-access
            gateway,
            "_client",
            cached_client,
        )
        with patch(
            "mugen.core.gateway.knowledge.weaviate.asyncio.to_thread",
            new=AsyncMock(),
        ) as to_thread:
            client = await gateway._get_client()  # pylint: disable=protected-access
        self.assertIs(client, cached_client)
        to_thread.assert_not_awaited()

        cached_collection = object()
        gateway._collection = None  # pylint: disable=protected-access
        gateway._collection_lock = _LockThatSetsAttr(  # pylint: disable=protected-access
            gateway,
            "_collection",
            cached_collection,
        )
        gateway._get_client = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access
        collection = await gateway._get_collection()  # pylint: disable=protected-access
        self.assertIs(collection, cached_collection)
        gateway._get_client.assert_not_awaited()  # pylint: disable=protected-access

        cached_encoder = object()
        gateway._encoder = None  # pylint: disable=protected-access
        gateway._encoder_lock = _LockThatSetsAttr(  # pylint: disable=protected-access
            gateway,
            "_encoder",
            cached_encoder,
        )
        with patch(
            "mugen.core.gateway.knowledge.weaviate.asyncio.to_thread",
            new=AsyncMock(),
        ) as to_thread:
            encoder = await gateway._get_encoder()  # pylint: disable=protected-access
        self.assertIs(encoder, cached_encoder)
        to_thread.assert_not_awaited()

    def test_normalization_helper_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())

        self.assertEqual(
            WeaviateKnowledgeGateway._normalize_optional_filter("  web  "),  # pylint: disable=protected-access
            "web",
        )
        self.assertIsNone(
            WeaviateKnowledgeGateway._normalize_optional_filter("  ")  # pylint: disable=protected-access
        )
        self.assertIsNone(
            WeaviateKnowledgeGateway._normalize_optional_filter(1)  # pylint: disable=protected-access
        )

        self.assertEqual(
            WeaviateKnowledgeGateway._normalize_search_term("  hello  "),  # pylint: disable=protected-access
            "hello",
        )
        with self.assertRaisesRegex(ValueError, "search_term must be a string"):
            WeaviateKnowledgeGateway._normalize_search_term(1)  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "search_term must be non-empty"):
            WeaviateKnowledgeGateway._normalize_search_term("  ")  # pylint: disable=protected-access

        tenant_uuid = uuid.uuid4()
        self.assertEqual(
            WeaviateKnowledgeGateway._normalize_tenant_id(tenant_uuid),  # pylint: disable=protected-access
            str(tenant_uuid),
        )
        with self.assertRaisesRegex(ValueError, "tenant_id must be a UUID"):
            WeaviateKnowledgeGateway._normalize_tenant_id(1)  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            WeaviateKnowledgeGateway._normalize_tenant_id("nope")  # pylint: disable=protected-access

        self.assertEqual(gateway._resolve_effective_top_k(None), 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_effective_top_k("bad"), 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_effective_top_k(0), 1)  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_effective_top_k(100), 50)  # pylint: disable=protected-access

        self.assertIsNone(
            WeaviateKnowledgeGateway._normalize_min_similarity(None)  # pylint: disable=protected-access
        )
        self.assertEqual(
            WeaviateKnowledgeGateway._normalize_min_similarity(0.25),  # pylint: disable=protected-access
            0.25,
        )
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            WeaviateKnowledgeGateway._normalize_min_similarity("bad")  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            WeaviateKnowledgeGateway._normalize_min_similarity(float("inf"))  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            WeaviateKnowledgeGateway._normalize_min_similarity(2.0)  # pylint: disable=protected-access

        self.assertEqual(
            WeaviateKnowledgeGateway._normalize_uuid_text(  # pylint: disable=protected-access
                tenant_uuid,
                field_name="tenant_id",
            ),
            str(tenant_uuid),
        )
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            WeaviateKnowledgeGateway._normalize_uuid_text(  # pylint: disable=protected-access
                1,
                field_name="tenant_id",
            )
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            WeaviateKnowledgeGateway._normalize_uuid_text(  # pylint: disable=protected-access
                " ",
                field_name="tenant_id",
            )
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            WeaviateKnowledgeGateway._normalize_uuid_text(  # pylint: disable=protected-access
                "invalid",
                field_name="tenant_id",
            )

        self.assertEqual(gateway._coerce_optional_string(1), "1")  # pylint: disable=protected-access
        self.assertIsNone(gateway._coerce_optional_string(""))  # pylint: disable=protected-access
        self.assertEqual(gateway._coerce_float("1.25"), 1.25)  # pylint: disable=protected-access
        self.assertIsNone(gateway._coerce_float("bad"))  # pylint: disable=protected-access

        long_text = "x" * 1000
        snippet = gateway._build_snippet(title=None, body=long_text)  # pylint: disable=protected-access
        self.assertEqual(len(snippet), 240)

        self.assertEqual(
            WeaviateKnowledgeGateway._extract_query_objects([1, 2]),  # pylint: disable=protected-access
            [1, 2],
        )
        self.assertEqual(
            WeaviateKnowledgeGateway._extract_query_objects({"objects": [1]}),  # pylint: disable=protected-access
            [1],
        )
        self.assertEqual(
            WeaviateKnowledgeGateway._extract_query_objects(  # pylint: disable=protected-access
                SimpleNamespace(objects=[1, 2, 3])
            ),
            [1, 2, 3],
        )
        with self.assertRaisesRegex(RuntimeError, "invalid query payload"):
            WeaviateKnowledgeGateway._extract_query_objects(  # pylint: disable=protected-access
                {"items": []}
            )

        self.assertEqual(
            WeaviateKnowledgeGateway._extract_properties(  # pylint: disable=protected-access
                {"properties": {"a": 1}}
            ),
            {"a": 1},
        )
        self.assertEqual(
            WeaviateKnowledgeGateway._extract_properties({"a": 1}),  # pylint: disable=protected-access
            {"a": 1},
        )
        self.assertEqual(
            WeaviateKnowledgeGateway._extract_properties(  # pylint: disable=protected-access
                SimpleNamespace(properties={"b": 2})
            ),
            {"b": 2},
        )
        self.assertEqual(
            WeaviateKnowledgeGateway._extract_properties(  # pylint: disable=protected-access
                SimpleNamespace(properties=_PropertiesWithModelDump())
            ),
            {"x": 1},
        )
        self.assertEqual(
            WeaviateKnowledgeGateway._extract_properties(  # pylint: disable=protected-access
                SimpleNamespace(properties=_PropertiesWithDict())
            ),
            {"y": 2},
        )
        self.assertEqual(
            WeaviateKnowledgeGateway._extract_properties(  # pylint: disable=protected-access
                SimpleNamespace(properties=_PropertiesWithAttrs())
            ),
            {"z": 3},
        )
        self.assertEqual(
            WeaviateKnowledgeGateway._extract_properties(  # pylint: disable=protected-access
                SimpleNamespace(properties=None)
            ),
            {},
        )

        self.assertEqual(
            gateway._extract_distance({"metadata": {"distance": 0.25}}),  # pylint: disable=protected-access
            0.25,
        )
        self.assertEqual(
            gateway._extract_distance({"distance": 0.5}),  # pylint: disable=protected-access
            0.5,
        )
        self.assertEqual(
            gateway._extract_distance(  # pylint: disable=protected-access
                SimpleNamespace(metadata={"distance": 0.75})
            ),
            0.75,
        )
        self.assertEqual(
            gateway._extract_distance(  # pylint: disable=protected-access
                SimpleNamespace(metadata=SimpleNamespace(distance=0.8))
            ),
            0.8,
        )
        self.assertEqual(
            gateway._extract_distance(SimpleNamespace(distance=0.9)),  # pylint: disable=protected-access
            0.9,
        )

    def test_query_filter_and_metadata_factory(self) -> None:
        filter_calls: list[tuple[str, str, object]] = []

        class _FilterExpression:
            def __init__(self, key: str):
                self.key = key

            def equal(self, value: object) -> tuple[str, str, object]:
                expression = ("eq", self.key, value)
                filter_calls.append(expression)
                return expression

        class _Filter:  # pylint: disable=too-few-public-methods
            @staticmethod
            def by_property(key: str) -> _FilterExpression:
                return _FilterExpression(key)

            @staticmethod
            def all_of(filters: list[object]) -> tuple[str, list[object]]:
                return ("all_of", list(filters))

        class _MetadataQuery:  # pylint: disable=too-few-public-methods
            def __init__(self, *, distance: bool):
                self.distance = distance

        query_module = ModuleType("weaviate.classes.query")
        query_module.Filter = _Filter
        query_module.MetadataQuery = _MetadataQuery

        with patch.dict(
            sys.modules,
            {
                "weaviate": ModuleType("weaviate"),
                "weaviate.classes": ModuleType("weaviate.classes"),
                "weaviate.classes.query": query_module,
            },
        ):
            only_tenant = WeaviateKnowledgeGateway._build_query_filters(  # pylint: disable=protected-access
                tenant_id=str(uuid.uuid4()),
                channel=None,
                locale=None,
                category=None,
            )
            self.assertEqual(only_tenant[0], "eq")

            scoped = WeaviateKnowledgeGateway._build_query_filters(  # pylint: disable=protected-access
                tenant_id=str(uuid.uuid4()),
                channel="web",
                locale="en-US",
                category="billing",
            )
            self.assertEqual(scoped[0], "all_of")
            self.assertEqual(len(scoped[1]), 4)

            metadata = WeaviateKnowledgeGateway._metadata_query_factory()  # pylint: disable=protected-access
            self.assertTrue(metadata.distance)
            self.assertGreaterEqual(len(filter_calls), 5)

    async def test_readiness_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())

        ready_client = SimpleNamespace(
            is_ready=Mock(return_value=True),
            collections=SimpleNamespace(exists=Mock(return_value=True)),
        )
        gateway._get_client = AsyncMock(return_value=ready_client)  # type: ignore[method-assign]  # pylint: disable=protected-access
        gateway._get_encoder = AsyncMock(return_value=object())  # type: ignore[method-assign]  # pylint: disable=protected-access
        await gateway.check_readiness()
        ready_client.is_ready.assert_called_once_with()
        ready_client.collections.exists.assert_called_once_with("DownstreamKPSearchDoc")
        gateway._get_encoder.assert_awaited_once_with()  # pylint: disable=protected-access

        gateway._get_client = AsyncMock(return_value=SimpleNamespace())  # type: ignore[method-assign]  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "probe is unavailable"):
            await gateway.check_readiness()

        gateway._get_client = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value=SimpleNamespace(
                is_ready=Mock(return_value=False),
                collections=SimpleNamespace(exists=Mock(return_value=True)),
            )
        )
        with self.assertRaisesRegex(RuntimeError, "probe failed"):
            await gateway.check_readiness()

        gateway._get_client = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value=SimpleNamespace(
                is_ready=Mock(return_value=True),
                collections=SimpleNamespace(),
            )
        )
        with self.assertRaisesRegex(RuntimeError, "collection probe is unavailable"):
            await gateway.check_readiness()

        gateway._get_client = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value=SimpleNamespace(
                is_ready=Mock(return_value=True),
                collections=SimpleNamespace(exists=Mock(return_value=False)),
            )
        )
        with self.assertRaisesRegex(RuntimeError, "configured collection was not found"):
            await gateway.check_readiness()

        gateway._get_client = AsyncMock(return_value=ready_client)  # type: ignore[method-assign]  # pylint: disable=protected-access
        gateway._get_encoder = AsyncMock(side_effect=RuntimeError("encoder"))  # type: ignore[method-assign]  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "encoder initialization failed"):
            await gateway.check_readiness()

        gateway._closed = True  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "is closed"):
            await gateway.check_readiness()

        gateway._closed = False  # pylint: disable=protected-access
        gateway._api_timeout_seconds = None  # pylint: disable=protected-access
        gateway._get_client = AsyncMock(return_value=ready_client)  # type: ignore[method-assign]  # pylint: disable=protected-access
        gateway._get_encoder = AsyncMock(return_value=object())  # type: ignore[method-assign]  # pylint: disable=protected-access
        timeouts: list[float] = []

        async def _wait_for(awaitable, timeout):
            timeouts.append(float(timeout))
            return await awaitable

        with patch(
            "mugen.core.gateway.knowledge.weaviate.asyncio.wait_for",
            side_effect=_wait_for,
        ):
            await gateway.check_readiness()
        self.assertEqual(timeouts, [5.0, 5.0, 5.0, 5.0])

    async def test_query_collection_and_search_paths(self) -> None:
        gateway, logger = _build_gateway(config=_make_config(target_vector="tenant_vector"))

        query_mock = Mock(
            return_value=SimpleNamespace(
                objects=[
                    _QueryObject(properties=_payload(body="A" * 500), distance=0.2),
                    _QueryObject(properties=_payload(body="short"), distance=0.9),
                ]
            )
        )
        gateway._get_collection = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value=SimpleNamespace(query=SimpleNamespace(near_vector=query_mock))
        )
        gateway._metadata_query_factory = Mock(return_value="metadata")  # type: ignore[method-assign]  # pylint: disable=protected-access
        gateway._build_query_filters = Mock(return_value="filters")  # type: ignore[method-assign]  # pylint: disable=protected-access
        gateway._encode_search_term = AsyncMock(return_value=[0.1, 0.2])  # type: ignore[method-assign]  # pylint: disable=protected-access

        params = WeaviateSearchVendorParams(
            search_term="how do I reset password?",
            tenant_id=uuid.uuid4(),
            top_k=15,
            min_similarity=0.5,
            channel="web",
            locale="en-US",
            category="billing",
        )
        result = await gateway.search(params)

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.raw_vendor["provider"], "weaviate")
        self.assertEqual(result.raw_vendor["collection"], "DownstreamKPSearchDoc")
        self.assertEqual(result.raw_vendor["target_vector"], "tenant_vector")
        self.assertEqual(result.raw_vendor["top_k"], 15)
        self.assertEqual(result.raw_vendor["result_count"], 1)
        self.assertLessEqual(len(result.items[0]["snippet"]), 240)
        self.assertGreater(result.items[0]["similarity"], 0.5)

        query_mock.assert_called_once()
        query_kwargs = query_mock.call_args.kwargs
        self.assertEqual(query_kwargs["near_vector"], [0.1, 0.2])
        self.assertEqual(query_kwargs["limit"], 15)
        self.assertEqual(query_kwargs["filters"], "filters")
        self.assertEqual(query_kwargs["target_vector"], "tenant_vector")
        self.assertEqual(query_kwargs["return_metadata"], "metadata")
        self.assertEqual(
            query_kwargs["return_properties"],
            list(gateway._required_properties),  # pylint: disable=protected-access
        )

        failing_query = Mock(side_effect=RuntimeError("boom"))
        gateway._get_collection = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value=SimpleNamespace(query=SimpleNamespace(near_vector=failing_query))
        )
        with self.assertRaises(KnowledgeGatewayRuntimeError) as raised:
            await gateway.search(params)
        self.assertEqual(raised.exception.provider, "weaviate")
        self.assertEqual(raised.exception.operation, "search")
        self.assertIn(
            "WeaviateKnowledgeGateway transport failure ",
            str(logger.warning.call_args_list[-1].args[0]),
        )

        gateway._closed = True  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "is closed"):
            await gateway.search(params)

        gateway._closed = False  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "search_term must be non-empty"):
            await gateway.search(
                WeaviateSearchVendorParams(
                    search_term=" ",
                    tenant_id=uuid.uuid4(),
                )
            )

    async def test_query_collection_validation_and_item_normalization(self) -> None:
        gateway, _ = _build_gateway(config=_make_config(target_vector=""))
        gateway._metadata_query_factory = Mock(return_value="metadata")  # type: ignore[method-assign]  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "query API is unavailable"):
            gateway._get_collection = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
                return_value=SimpleNamespace(query=SimpleNamespace())
            )
            await gateway._query_collection(  # pylint: disable=protected-access
                query_vector=[0.1],
                query_filters="f",
                top_k=1,
            )

        with self.assertRaisesRegex(RuntimeError, "invalid query payload"):
            gateway._get_collection = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
                return_value=SimpleNamespace(
                    query=SimpleNamespace(near_vector=Mock(return_value={"items": []}))
                )
            )
            await gateway._query_collection(  # pylint: disable=protected-access
                query_vector=[0.1],
                query_filters="f",
                top_k=1,
            )

        with self.assertRaisesRegex(RuntimeError, "missing required property key"):
            gateway._normalise_item(  # pylint: disable=protected-access
                item=_QueryObject(properties={"tenant_id": str(uuid.uuid4())}, distance=0.1)
            )

        object_without_distance = _QueryObject(
            properties=_payload(body=None, title="fallback"),
            distance=None,
        )
        items = gateway._normalise_items(  # pylint: disable=protected-access
            query_result=SimpleNamespace(objects=[object_without_distance]),
            min_similarity=0.1,
        )
        self.assertEqual(items, [])

    async def test_execute_with_retry_and_close(self) -> None:
        gateway, logger = _build_gateway(config=_make_config())

        attempts = {"count": 0}

        async def _flaky():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("temporary")
            return "ok"

        gateway._api_max_retries = 2  # pylint: disable=protected-access
        gateway._api_retry_backoff_seconds = 0.25  # pylint: disable=protected-access
        with patch("mugen.core.gateway.knowledge.weaviate.asyncio.sleep", new=AsyncMock()) as sleep:
            value = await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=_flaky,
            )
        self.assertEqual(value, "ok")
        sleep.assert_awaited_once_with(0.25)
        self.assertTrue(logger.warning.called)

        attempts_no_sleep = {"count": 0}

        async def _flaky_no_sleep():
            attempts_no_sleep["count"] += 1
            if attempts_no_sleep["count"] == 1:
                raise RuntimeError("temporary")
            return "ok-no-sleep"

        gateway._api_max_retries = 2  # pylint: disable=protected-access
        gateway._api_retry_backoff_seconds = 0.0  # pylint: disable=protected-access
        with patch("mugen.core.gateway.knowledge.weaviate.asyncio.sleep", new=AsyncMock()) as sleep:
            value = await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=_flaky_no_sleep,
            )
        self.assertEqual(value, "ok-no-sleep")
        sleep.assert_not_awaited()

        gateway._api_max_retries = 1  # pylint: disable=protected-access
        gateway._api_retry_backoff_seconds = 0.25  # pylint: disable=protected-access
        with patch("mugen.core.gateway.knowledge.weaviate.asyncio.sleep", new=AsyncMock()) as sleep:
            with self.assertRaisesRegex(RuntimeError, "permanent"):
                await gateway._execute_with_retry(  # pylint: disable=protected-access
                    operation="search",
                    request_factory=AsyncMock(side_effect=RuntimeError("permanent")),
                )
        sleep.assert_awaited_once_with(0.25)

        sync_closed: list[str] = []
        gateway._client = SimpleNamespace(close=lambda: sync_closed.append("sync"))  # pylint: disable=protected-access
        await gateway.aclose()
        self.assertEqual(sync_closed, ["sync"])
        await gateway.aclose()

        async_closed: list[str] = []

        async def _async_close():
            async_closed.append("async")
            return None

        other_gateway, _ = _build_gateway(config=_make_config())
        other_gateway._client = SimpleNamespace(close=_async_close)  # pylint: disable=protected-access
        await other_gateway.aclose()
        self.assertEqual(async_closed, ["async"])

        no_close_gateway, _ = _build_gateway(config=_make_config())
        no_close_gateway._client = SimpleNamespace()  # pylint: disable=protected-access
        await no_close_gateway.aclose()
