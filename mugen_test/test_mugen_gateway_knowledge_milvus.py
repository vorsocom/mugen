"""Unit tests for mugen.core.gateway.knowledge.milvus.MilvusKnowledgeGateway."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from mugen.core.contract.dto.milvus.search import MilvusSearchVendorParams
from mugen.core.contract.gateway.knowledge import KnowledgeGatewayRuntimeError
from mugen.core.gateway.knowledge.milvus import MilvusKnowledgeGateway


class _VectorLike:
    def tolist(self) -> list[float]:
        return [0.1, 0.2]


class _IterableVector:
    def __iter__(self):
        return iter([0.3, 0.4])


class _HitObject:
    def __init__(self, *, entity: dict, score: object, distance: object) -> None:
        self.entity = entity
        self.score = score
        self.distance = distance


def _make_config(
    *,
    uri: object = "http://localhost:19530",
    token: object = "",
    timeout_seconds: object = 2.5,
    max_retries: object = 0,
    retry_backoff_seconds: object = 0.0,
    collection: object = "downstream_kp_search_doc",
    vector_field: object = "embedding",
    default_top_k: object = 10,
    max_top_k: object = 50,
    snippet_max_chars: object = 240,
    encoder_model: object = "all-mpnet-base-v2",
    encoder_max_concurrency: object = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        milvus=SimpleNamespace(
            api=SimpleNamespace(
                uri=uri,
                token=token,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            ),
            search=SimpleNamespace(
                collection=collection,
                vector_field=vector_field,
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
) -> tuple[MilvusKnowledgeGateway, Mock]:
    logger = logging_gateway or Mock()
    gateway = MilvusKnowledgeGateway(config, logger)
    return gateway, logger


def _payload(
    *,
    tenant_id: str | None = None,
    revision_id: str | None = None,
    version_id: str | None = None,
) -> dict:
    return {
        "tenant_id": tenant_id or str(uuid.uuid4()),
        "knowledge_entry_revision_id": revision_id or str(uuid.uuid4()),
        "knowledge_pack_version_id": version_id or str(uuid.uuid4()),
        "channel": "web",
        "locale": "en-US",
        "category": "billing",
        "title": "Title",
        "body": "Body text",
    }


class TestMugenGatewayKnowledgeMilvus(unittest.IsolatedAsyncioTestCase):
    """Coverage for Milvus knowledge gateway parsing, readiness, and search."""

    def test_config_defaults_and_validation(self) -> None:
        gateway, _ = _build_gateway(
            config=_make_config(
                uri=None,
                token=123,
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
        self.assertEqual(gateway._api_uri, "")  # pylint: disable=protected-access
        self.assertIsNone(gateway._api_token)  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._api_timeout_seconds  # pylint: disable=protected-access
        )
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
            gateway._search_vector_field,  # pylint: disable=protected-access
            "embedding",
        )
        self.assertEqual(
            gateway._encoder_model_name,  # pylint: disable=protected-access
            "all-mpnet-base-v2",
        )
        self.assertEqual(
            gateway._encoder_max_concurrency, 4
        )  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._section("milvus", "missing")
        )  # pylint: disable=protected-access

        with self.assertRaisesRegex(
            RuntimeError, "milvus.search.collection is required"
        ):
            _build_gateway(config=_make_config(collection="  "))

        with self.assertRaisesRegex(RuntimeError, "milvus.search.vector_field"):
            _build_gateway(config=_make_config(vector_field=" "))

        vector_field_default_gateway, _ = _build_gateway(
            config=_make_config(vector_field=123)
        )
        self.assertEqual(
            vector_field_default_gateway._search_vector_field,  # pylint: disable=protected-access
            "embedding",
        )

        with self.assertRaisesRegex(RuntimeError, "milvus.search.default_top_k"):
            _build_gateway(config=_make_config(default_top_k=True))

        with self.assertRaisesRegex(RuntimeError, "milvus.search.max_top_k"):
            _build_gateway(config=_make_config(max_top_k=0))

        with self.assertRaisesRegex(RuntimeError, "milvus.search.snippet_max_chars"):
            _build_gateway(config=_make_config(snippet_max_chars=0))

        with self.assertRaisesRegex(RuntimeError, "milvus.api.timeout_seconds"):
            _build_gateway(config=_make_config(timeout_seconds=0))

        with self.assertRaisesRegex(RuntimeError, "milvus.api.retry_backoff_seconds"):
            _build_gateway(config=_make_config(retry_backoff_seconds=-1))

    def test_constructor_warnings_and_helper_branches(self) -> None:
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
            "MilvusKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k.",
            warnings,
        )
        self.assertIn(
            "MilvusKnowledgeGateway: Invalid max_retries configuration.",
            warnings,
        )

        _build_gateway(
            config=_make_config(max_retries=-1),
            logging_gateway=logger,
        )
        warnings = [str(call.args[0]) for call in logger.warning.call_args_list]
        self.assertIn(
            "MilvusKnowledgeGateway: max_retries must be non-negative.",
            warnings,
        )

        with self.assertRaisesRegex(RuntimeError, "must be a positive integer"):
            MilvusKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                object(),
                field_name="field",
                default=1,
            )
        with self.assertRaisesRegex(RuntimeError, "must be a positive integer"):
            MilvusKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                True,
                field_name="field",
                default=1,
            )
        with self.assertRaisesRegex(RuntimeError, "greater than 0"):
            MilvusKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                0,
                field_name="field",
                default=1,
            )

        gateway._config.milvus.encoder.model = 123  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_encoder_model_name(),  # pylint: disable=protected-access
            "all-mpnet-base-v2",
        )
        gateway._config.milvus.encoder.model = "  "  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_encoder_model_name(),  # pylint: disable=protected-access
            "all-mpnet-base-v2",
        )

    def test_create_and_build_client_paths(self) -> None:
        fake_client = Mock(return_value=object())
        with patch.dict(
            sys.modules,
            {"pymilvus": SimpleNamespace(MilvusClient=fake_client)},
        ):
            built = MilvusKnowledgeGateway._create_client(
                uri="http://localhost"
            )  # pylint: disable=protected-access
        self.assertIsNotNone(built)
        fake_client.assert_called_once_with(uri="http://localhost")

        gateway, _ = _build_gateway(config=_make_config(uri=""))
        with self.assertRaisesRegex(RuntimeError, "requires milvus.api.uri"):
            gateway._build_client()  # pylint: disable=protected-access

        gateway, _ = _build_gateway(
            config=_make_config(
                uri="http://milvus.local:19530",
                token="secret-token",
                timeout_seconds=8.0,
            )
        )
        with patch.object(
            gateway, "_create_client", return_value=object()
        ) as create_client:
            gateway._build_client()  # pylint: disable=protected-access
        create_client.assert_called_once_with(
            uri="http://milvus.local:19530",
            token="secret-token",
            timeout=8.0,
        )

        gateway, _ = _build_gateway(
            config=_make_config(
                uri="http://milvus.local:19530",
                token=None,
                timeout_seconds=None,
            )
        )
        with patch.object(
            gateway, "_create_client", return_value=object()
        ) as create_client:
            gateway._build_client()  # pylint: disable=protected-access
        create_client.assert_called_once_with(
            uri="http://milvus.local:19530",
        )

    async def test_get_client_encoder_and_encoding_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())
        gateway._build_client = Mock(
            return_value=object()
        )  # pylint: disable=protected-access
        first_client = await gateway._get_client()  # pylint: disable=protected-access
        second_client = await gateway._get_client()  # pylint: disable=protected-access
        self.assertIs(first_client, second_client)
        gateway._build_client.assert_called_once_with()  # pylint: disable=protected-access

        race_gateway, _ = _build_gateway(config=_make_config())

        def _slow_build_client():
            import time

            time.sleep(0.05)
            return object()

        race_gateway._build_client = (
            _slow_build_client  # pylint: disable=protected-access
        )
        first_client, second_client = await asyncio.gather(
            race_gateway._get_client(),  # pylint: disable=protected-access
            race_gateway._get_client(),  # pylint: disable=protected-access
        )
        self.assertIs(first_client, second_client)

        with patch(
            "mugen.core.gateway.knowledge.milvus.SentenceTransformer"
        ) as transformer:
            built_encoder = gateway._build_encoder()  # pylint: disable=protected-access
        self.assertIs(built_encoder, transformer.return_value)
        transformer.assert_called_once_with(
            model_name_or_path="all-mpnet-base-v2",
            tokenizer_kwargs={"clean_up_tokenization_spaces": False},
            cache_folder="/tmp/hf",
        )

        gateway._encoder = None  # pylint: disable=protected-access
        gateway._build_encoder = Mock(
            return_value="encoder"
        )  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._get_encoder(), "encoder"
        )  # pylint: disable=protected-access
        self.assertEqual(
            await gateway._get_encoder(), "encoder"
        )  # pylint: disable=protected-access
        gateway._build_encoder.assert_called_once_with()  # pylint: disable=protected-access

        race_encoder_gateway, _ = _build_gateway(config=_make_config())

        def _slow_build_encoder():
            import time

            time.sleep(0.05)
            return object()

        race_encoder_gateway._build_encoder = (
            _slow_build_encoder  # pylint: disable=protected-access
        )
        first_encoder, second_encoder = await asyncio.gather(
            race_encoder_gateway._get_encoder(),  # pylint: disable=protected-access
            race_encoder_gateway._get_encoder(),  # pylint: disable=protected-access
        )
        self.assertIs(first_encoder, second_encoder)

        encoder = Mock()
        gateway._get_encoder = AsyncMock(
            return_value=encoder
        )  # pylint: disable=protected-access
        encoder.encode.return_value = _VectorLike()
        self.assertEqual(
            await gateway._encode_search_term("a"), [0.1, 0.2]
        )  # pylint: disable=protected-access
        encoder.encode.return_value = [0.5, 0.6]
        self.assertEqual(
            await gateway._encode_search_term("b"), [0.5, 0.6]
        )  # pylint: disable=protected-access
        encoder.encode.return_value = _IterableVector()
        self.assertEqual(
            await gateway._encode_search_term("c"), [0.3, 0.4]
        )  # pylint: disable=protected-access

    def test_normalizers_and_filter_building(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())

        self.assertEqual(
            gateway._normalize_optional_filter(
                " value "
            ),  # pylint: disable=protected-access
            "value",
        )
        self.assertIsNone(
            gateway._normalize_optional_filter(1)
        )  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._normalize_optional_filter(" ")
        )  # pylint: disable=protected-access

        with self.assertRaisesRegex(ValueError, "search_term must be a string"):
            gateway._normalize_search_term(1)  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "search_term must be non-empty"):
            gateway._normalize_search_term("  ")  # pylint: disable=protected-access
        self.assertEqual(
            gateway._normalize_search_term(" ok "), "ok"
        )  # pylint: disable=protected-access

        parsed_tenant_id = gateway._normalize_tenant_id(
            str(uuid.uuid4())
        )  # pylint: disable=protected-access
        self.assertTrue(uuid.UUID(parsed_tenant_id))
        self.assertEqual(
            gateway._normalize_tenant_id(
                uuid.UUID(parsed_tenant_id)
            ),  # pylint: disable=protected-access
            parsed_tenant_id,
        )
        with self.assertRaisesRegex(ValueError, "tenant_id must be a UUID"):
            gateway._normalize_tenant_id(1)  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            gateway._normalize_tenant_id("bad-uuid")  # pylint: disable=protected-access

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
            gateway._resolve_effective_top_k(999), 50
        )  # pylint: disable=protected-access

        self.assertIsNone(
            gateway._normalize_min_similarity(None)
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._normalize_min_similarity(0.5), 0.5
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "min_similarity"):
            gateway._normalize_min_similarity("bad")  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "min_similarity"):
            gateway._normalize_min_similarity(
                float("inf")
            )  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "min_similarity"):
            gateway._normalize_min_similarity(-1)  # pylint: disable=protected-access

        parsed_uuid = str(uuid.uuid4())
        self.assertEqual(
            gateway._normalize_uuid_text(  # pylint: disable=protected-access
                parsed_uuid,
                field_name="tenant_id",
            ),
            parsed_uuid,
        )
        parsed_uuid_obj = uuid.uuid4()
        self.assertEqual(
            gateway._normalize_uuid_text(  # pylint: disable=protected-access
                parsed_uuid_obj,
                field_name="tenant_id",
            ),
            str(parsed_uuid_obj),
        )
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            gateway._normalize_uuid_text(
                1, field_name="tenant_id"
            )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            gateway._normalize_uuid_text(
                "", field_name="tenant_id"
            )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            gateway._normalize_uuid_text(
                "bad-uuid", field_name="tenant_id"
            )  # pylint: disable=protected-access

        self.assertEqual(
            gateway._coerce_optional_string(1), "1"
        )  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._coerce_optional_string("")
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._coerce_optional_string(" "), " "
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._coerce_float("1.5"), 1.5
        )  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._coerce_float("bad")
        )  # pylint: disable=protected-access

        self.assertEqual(
            gateway._build_snippet(  # pylint: disable=protected-access
                title="title",
                body="body",
            ),
            "body",
        )
        gateway._snippet_max_chars = 4  # pylint: disable=protected-access
        self.assertEqual(
            gateway._build_snippet(  # pylint: disable=protected-access
                title="title",
                body="body-text",
            ),
            "body",
        )
        self.assertIsNone(
            gateway._build_snippet(
                title=None, body=None
            )  # pylint: disable=protected-access
        )

        self.assertEqual(
            gateway._escape_filter_value('x"\\y'),  # pylint: disable=protected-access
            'x\\"\\\\y',
        )
        filter_expression = (
            gateway._build_filter_expression(  # pylint: disable=protected-access
                tenant_id=parsed_uuid,
                channel="web",
                locale="en",
                category="billing",
            )
        )
        self.assertIn('tenant_id == "', filter_expression)
        self.assertIn('channel == "web"', filter_expression)
        self.assertIn('locale == "en"', filter_expression)
        self.assertIn('category == "billing"', filter_expression)

    def test_hit_extraction_and_normalization_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())
        payload = _payload()

        self.assertEqual(
            gateway._extract_hits("bad"), []
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._extract_hits([]), []
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._extract_hits([[{"id": 1}]])[
                :1
            ],  # pylint: disable=protected-access
            [{"id": 1}],
        )
        self.assertEqual(
            gateway._extract_hits([{"id": 2}]),  # pylint: disable=protected-access
            [{"id": 2}],
        )

        entity_payload, score, distance = (
            gateway._extract_hit_payload(  # pylint: disable=protected-access
                {"entity": payload, "score": 0.8, "distance": 0.2}
            )
        )
        self.assertEqual(entity_payload, payload)
        self.assertEqual(score, 0.8)
        self.assertEqual(distance, 0.2)

        flat_payload, _, _ = gateway._extract_hit_payload(
            payload
        )  # pylint: disable=protected-access
        self.assertEqual(flat_payload["title"], "Title")

        object_payload, obj_score, obj_distance = (
            gateway._extract_hit_payload(  # pylint: disable=protected-access
                _HitObject(entity=payload, score=0.7, distance=0.3)
            )
        )
        self.assertEqual(object_payload, payload)
        self.assertEqual(obj_score, 0.7)
        self.assertEqual(obj_distance, 0.3)

        with self.assertRaisesRegex(RuntimeError, "hit payload is invalid"):
            gateway._extract_hit_payload(object())  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "missing required key"):
            gateway._normalise_item(  # pylint: disable=protected-access
                payload={"tenant_id": str(uuid.uuid4())},
                score_raw=0.5,
                distance_raw=0.5,
            )

        normalized_from_score = (
            gateway._normalise_item(  # pylint: disable=protected-access
                payload=payload,
                score_raw=0.8,
                distance_raw=None,
            )
        )
        self.assertEqual(normalized_from_score["similarity"], 0.8)
        self.assertAlmostEqual(normalized_from_score["distance"], 0.2)

        normalized_from_distance = (
            gateway._normalise_item(  # pylint: disable=protected-access
                payload=payload,
                score_raw=None,
                distance_raw=0.3,
            )
        )
        self.assertEqual(normalized_from_distance["similarity"], 0.7)
        self.assertEqual(normalized_from_distance["distance"], 0.3)

        items = gateway._normalise_items(  # pylint: disable=protected-access
            search_result=[[{"entity": payload, "score": 0.4}]],
            min_similarity=0.5,
        )
        self.assertEqual(items, [])

    async def test_query_collection_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())
        gateway._client = SimpleNamespace()  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "search API is unavailable"):
            await gateway._query_collection(  # pylint: disable=protected-access
                query_vector=[0.1, 0.2],
                filter_expression='tenant_id == "x"',
                top_k=3,
            )

        calls: list[dict] = []

        def _search_invalid(**kwargs):
            calls.append(kwargs)
            return {"bad": "shape"}

        gateway._client = SimpleNamespace(
            search=_search_invalid
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "invalid search payload"):
            await gateway._query_collection(  # pylint: disable=protected-access
                query_vector=[0.1, 0.2],
                filter_expression='tenant_id == "x"',
                top_k=3,
            )

        def _search_valid(**kwargs):
            calls.append(kwargs)
            return [[{"entity": _payload(), "score": 0.9}]]

        gateway._client = SimpleNamespace(
            search=_search_valid
        )  # pylint: disable=protected-access
        search_result = (
            await gateway._query_collection(  # pylint: disable=protected-access
                query_vector=[0.1, 0.2],
                filter_expression='tenant_id == "x"',
                top_k=3,
            )
        )
        self.assertEqual(len(search_result), 1)
        self.assertEqual(calls[-1]["collection_name"], "downstream_kp_search_doc")
        self.assertEqual(calls[-1]["anns_field"], "embedding")

    async def test_execute_retry_assert_open_and_close(self) -> None:
        logger = Mock()
        gateway, _ = _build_gateway(
            config=_make_config(max_retries=1, retry_backoff_seconds=0.0),
            logging_gateway=logger,
        )

        attempts = {"count": 0}

        async def _flaky():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("transient")
            return "ok"

        result = await gateway._execute_with_retry(  # pylint: disable=protected-access
            operation="search",
            request_factory=_flaky,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 2)
        self.assertGreaterEqual(logger.warning.call_count, 1)

        gateway._api_max_retries = 0  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "fatal"):
            await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=AsyncMock(side_effect=RuntimeError("fatal")),
            )

        gateway._api_max_retries = 1  # pylint: disable=protected-access
        gateway._api_retry_backoff_seconds = 0.5  # pylint: disable=protected-access
        sleep_mock = AsyncMock(return_value=None)
        with (
            patch("mugen.core.gateway.knowledge.milvus.asyncio.sleep", sleep_mock),
            self.assertRaisesRegex(RuntimeError, "again"),
        ):
            await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=AsyncMock(side_effect=RuntimeError("again")),
            )
        sleep_mock.assert_awaited()

        gateway._closed = True  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "is closed"):
            gateway._assert_open()  # pylint: disable=protected-access

        self.assertIsNone(await gateway.aclose())

        close_calls: list[str] = []
        gateway._closed = False  # pylint: disable=protected-access

        def _sync_close():
            close_calls.append("sync")
            return None

        gateway._client = SimpleNamespace(
            close=_sync_close
        )  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

        gateway._closed = False  # pylint: disable=protected-access

        async def _async_close():
            close_calls.append("async")
            return None

        gateway._client = SimpleNamespace(
            close=_async_close
        )  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())
        self.assertEqual(close_calls, ["sync", "async"])

        gateway._closed = False  # pylint: disable=protected-access
        gateway._client = object()  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

    async def test_check_readiness_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config(timeout_seconds=None))
        gateway._client = SimpleNamespace(
            list_collections=Mock(return_value=["downstream_kp_search_doc"])
        )  # pylint: disable=protected-access
        gateway._get_encoder = AsyncMock(
            return_value=object()
        )  # pylint: disable=protected-access

        timeouts: list[float] = []

        async def _wait_for(awaitable, timeout):
            timeouts.append(float(timeout))
            return await awaitable

        with patch(
            "mugen.core.gateway.knowledge.milvus.asyncio.wait_for",
            side_effect=_wait_for,
        ):
            await gateway.check_readiness()
        self.assertEqual(timeouts, [5.0, 5.0, 5.0])

        gateway._api_timeout_seconds = 2.5  # pylint: disable=protected-access
        with patch(
            "mugen.core.gateway.knowledge.milvus.asyncio.wait_for",
            side_effect=_wait_for,
        ):
            await gateway.check_readiness()
        self.assertEqual(timeouts[-3:], [2.5, 2.5, 2.5])

        gateway._api_uri = ""  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "requires milvus.api.uri"):
            await gateway.check_readiness()

        gateway._api_uri = "http://localhost:19530"  # pylint: disable=protected-access
        gateway._get_client = AsyncMock(
            return_value=SimpleNamespace()
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "probe is unavailable"):
            await gateway.check_readiness()

        gateway._get_client = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(
                list_collections=Mock(side_effect=RuntimeError("probe failed"))
            )
        )
        with self.assertRaisesRegex(RuntimeError, "probe failed"):
            await gateway.check_readiness()

        gateway._get_client = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(list_collections=Mock(return_value="bad"))
        )
        with self.assertRaisesRegex(RuntimeError, "invalid payload"):
            await gateway.check_readiness()

        gateway._get_client = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(list_collections=Mock(return_value=["other"]))
        )
        with self.assertRaisesRegex(RuntimeError, "collection was not found"):
            await gateway.check_readiness()

        gateway._get_client = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(
                list_collections=Mock(return_value=["downstream_kp_search_doc"])
            )
        )
        gateway._get_encoder = AsyncMock(
            side_effect=RuntimeError("encoder failed")
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "encoder initialization failed"):
            await gateway.check_readiness()

    async def test_search_success_and_failure_paths(self) -> None:
        tenant_id = uuid.uuid4()
        payload = _payload(tenant_id=str(tenant_id))
        gateway, logger = _build_gateway(config=_make_config())

        search_calls: list[dict] = []

        def _search(**kwargs):
            search_calls.append(kwargs)
            return [[{"entity": payload, "score": 0.85}]]

        gateway._client = SimpleNamespace(
            search=_search
        )  # pylint: disable=protected-access
        gateway._encode_search_term = AsyncMock(
            return_value=[0.1, 0.2]
        )  # pylint: disable=protected-access

        result = await gateway.search(
            MilvusSearchVendorParams(
                search_term="hello world",
                tenant_id=tenant_id,
                top_k=5,
                min_similarity=0.8,
                channel="web",
                locale="en-US",
                category="billing",
            )
        )
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.raw_vendor["provider"], "milvus")
        self.assertEqual(search_calls[0]["limit"], 5)
        self.assertIn('tenant_id == "', search_calls[0]["filter"])
        self.assertIn('channel == "web"', search_calls[0]["filter"])

        with self.assertRaisesRegex(ValueError, "search_term must be a string"):
            await gateway.search(
                MilvusSearchVendorParams(
                    search_term=123,  # type: ignore[arg-type]
                    tenant_id=tenant_id,
                )
            )

        gateway._execute_with_retry = AsyncMock(
            side_effect=RuntimeError("transport")
        )  # pylint: disable=protected-access
        with self.assertRaises(KnowledgeGatewayRuntimeError) as ctx:
            await gateway.search(
                MilvusSearchVendorParams(
                    search_term="hello",
                    tenant_id=tenant_id,
                )
            )
        self.assertEqual(ctx.exception.provider, "milvus")
        self.assertEqual(ctx.exception.operation, "search")
        logger.warning.assert_any_call(
            "MilvusKnowledgeGateway transport failure "
            "(operation=search error=RuntimeError: transport)"
        )
