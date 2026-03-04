"""Unit tests for mugen.core.gateway.knowledge.pinecone.PineconeKnowledgeGateway."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from mugen.core.contract.dto.pinecone.search import PineconeSearchVendorParams
from mugen.core.contract.gateway.knowledge import KnowledgeGatewayRuntimeError
from mugen.core.gateway.knowledge.pinecone import PineconeKnowledgeGateway


class _VectorLike:
    def tolist(self) -> list[float]:
        return [0.1, 0.2]


class _IterableVector:
    def __iter__(self):
        return iter([0.3, 0.4])


class _MatchObject:
    def __init__(self, *, metadata: dict, score: object) -> None:
        self.metadata = metadata
        self.score = score


class _MatchWithDict:
    def __init__(self, *, payload: object) -> None:
        self._payload = payload

    def dict(self):
        if isinstance(self._payload, dict):
            return dict(self._payload)
        return self._payload


class _QueryResultWithMatches:
    def __init__(self, matches: list[object]) -> None:
        self.matches = list(matches)


class _QueryResultWithModelDump:
    def __init__(self, matches: list[object]) -> None:
        self._matches = list(matches)

    def model_dump(self) -> dict:
        return {"matches": list(self._matches)}


class _QueryResultWithToDict:
    def __init__(self, matches: list[object]) -> None:
        self._matches = list(matches)

    def to_dict(self) -> dict:
        return {"matches": list(self._matches)}


def _make_config(
    *,
    environment: str = "development",
    api_key: object = "pinecone-api-key",
    api_host: object = "https://example-idx.svc.pinecone.io",
    timeout_seconds: object = 2.5,
    max_retries: object = 0,
    retry_backoff_seconds: object = 0.0,
    namespace: object = "",
    metric: object = "cosine",
    default_top_k: object = 10,
    max_top_k: object = 50,
    snippet_max_chars: object = 240,
    encoder_model: object = "all-mpnet-base-v2",
    encoder_max_concurrency: object = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(environment=environment),
        pinecone=SimpleNamespace(
            api=SimpleNamespace(
                key=api_key,
                host=api_host,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            ),
            search=SimpleNamespace(
                namespace=namespace,
                metric=metric,
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


def _build_gateway(
    *,
    config: SimpleNamespace,
    logging_gateway: Mock | None = None,
) -> tuple[PineconeKnowledgeGateway, Mock]:
    logger = logging_gateway or Mock()
    with patch("mugen.core.gateway.knowledge.pinecone.SentenceTransformer"):
        gateway = PineconeKnowledgeGateway(config, logger)
    return gateway, logger


class TestMugenGatewayKnowledgePinecone(unittest.IsolatedAsyncioTestCase):
    """Coverage for Pinecone knowledge gateway parsing, readiness, and search."""

    def test_config_defaults_and_validation(self) -> None:
        gateway, _ = _build_gateway(
            config=_make_config(
                timeout_seconds=None,
                namespace=None,
                metric="",
                default_top_k=None,
                max_top_k=None,
                snippet_max_chars=None,
                encoder_model=123,
                encoder_max_concurrency=0,
            )
        )
        self.assertIsNone(gateway._api_timeout_seconds)  # pylint: disable=protected-access
        self.assertIsNone(gateway._search_namespace)  # pylint: disable=protected-access
        self.assertEqual(gateway._search_metric, "cosine")  # pylint: disable=protected-access
        self.assertEqual(gateway._search_default_top_k, 10)  # pylint: disable=protected-access
        self.assertEqual(gateway._search_max_top_k, 50)  # pylint: disable=protected-access
        self.assertEqual(gateway._snippet_max_chars, 240)  # pylint: disable=protected-access
        self.assertEqual(gateway._encoder_model_name, "all-mpnet-base-v2")  # pylint: disable=protected-access
        self.assertEqual(gateway._encoder_max_concurrency, 4)  # pylint: disable=protected-access
        self.assertIsNone(gateway._section("pinecone", "missing"))  # pylint: disable=protected-access

        metric_default_gateway, _ = _build_gateway(config=_make_config(metric=123))
        self.assertEqual(
            metric_default_gateway._search_metric,  # pylint: disable=protected-access
            "cosine",
        )
        blank_model_gateway, _ = _build_gateway(config=_make_config(encoder_model="   "))
        self.assertEqual(
            blank_model_gateway._encoder_model_name,  # pylint: disable=protected-access
            "all-mpnet-base-v2",
        )

        with self.assertRaisesRegex(RuntimeError, "pinecone.api.key is required"):
            _build_gateway(config=_make_config(api_key="  "))
        with self.assertRaisesRegex(RuntimeError, "pinecone.api.host is required"):
            _build_gateway(config=_make_config(api_host="  "))
        with self.assertRaisesRegex(RuntimeError, "pinecone.search.metric"):
            _build_gateway(config=_make_config(metric="invalid"))
        with self.assertRaisesRegex(RuntimeError, "pinecone.search.default_top_k"):
            _build_gateway(config=_make_config(default_top_k=True))
        with self.assertRaisesRegex(RuntimeError, "pinecone.search.max_top_k"):
            _build_gateway(config=_make_config(max_top_k=0))
        with self.assertRaisesRegex(RuntimeError, "pinecone.search.snippet_max_chars"):
            _build_gateway(config=_make_config(snippet_max_chars=0))
        with self.assertRaisesRegex(RuntimeError, "pinecone.api.timeout_seconds"):
            _build_gateway(config=_make_config(timeout_seconds=0))
        with self.assertRaisesRegex(RuntimeError, "pinecone.api.retry_backoff_seconds"):
            _build_gateway(config=_make_config(retry_backoff_seconds=-1))
        with self.assertRaisesRegex(RuntimeError, "must be a positive integer"):
            PineconeKnowledgeGateway._parse_positive_int(  # pylint: disable=protected-access
                object(),
                field_name="field",
                default=1,
            )

    def test_constructor_warnings_and_production_timeout_policy(self) -> None:
        logger = Mock()
        _build_gateway(
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
            "PineconeKnowledgeGateway: default_top_k exceeds max_top_k; clamping to max_top_k.",
            warnings,
        )
        self.assertIn(
            "PineconeKnowledgeGateway: Invalid max_retries configuration.",
            warnings,
        )

        logger = Mock()
        _build_gateway(
            config=_make_config(max_retries=-1),
            logging_gateway=logger,
        )
        warnings = [str(call.args[0]) for call in logger.warning.call_args_list]
        self.assertIn(
            "PineconeKnowledgeGateway: max_retries must be non-negative.",
            warnings,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "PineconeKnowledgeGateway: Missing required production configuration field\\(s\\): timeout_seconds.",
        ):
            _build_gateway(
                config=_make_config(environment="production", timeout_seconds=None)
            )

        gateway = PineconeKnowledgeGateway.__new__(PineconeKnowledgeGateway)
        gateway._config = _make_config(  # pylint: disable=protected-access
            environment="production",
            timeout_seconds=None,
        )
        gateway._api_timeout_seconds = None  # pylint: disable=protected-access
        gateway._logging_gateway = Mock()  # pylint: disable=protected-access
        gateway._warn_missing_timeout_in_production()  # pylint: disable=protected-access
        gateway._logging_gateway.warning.assert_called_once_with(  # pylint: disable=protected-access
            "PineconeKnowledgeGateway: timeout_seconds is not configured in production."
        )

        gateway._api_timeout_seconds = 2.0  # pylint: disable=protected-access
        gateway._logging_gateway = Mock()  # pylint: disable=protected-access
        gateway._warn_missing_timeout_in_production()  # pylint: disable=protected-access
        gateway._logging_gateway.warning.assert_not_called()  # pylint: disable=protected-access

    def test_create_client_paths(self) -> None:
        fake_asyncio = Mock(return_value=object())
        with patch.dict(
            sys.modules,
            {"pinecone": SimpleNamespace(PineconeAsyncio=fake_asyncio)},
        ):
            client = PineconeKnowledgeGateway._create_client(api_key="k")  # pylint: disable=protected-access
        self.assertIsNotNone(client)
        fake_asyncio.assert_called_once_with(api_key="k")

        fake_sync = Mock(return_value=object())
        with patch.dict(
            sys.modules,
            {"pinecone": SimpleNamespace(Pinecone=fake_sync)},
        ):
            client = PineconeKnowledgeGateway._create_client(api_key="k")  # pylint: disable=protected-access
        self.assertIsNotNone(client)
        fake_sync.assert_called_once_with(api_key="k")

    async def test_client_index_encoder_and_encoding_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())
        gateway._create_client = Mock(return_value=object())  # pylint: disable=protected-access
        first_client = await gateway._get_client()  # pylint: disable=protected-access
        second_client = await gateway._get_client()  # pylint: disable=protected-access
        self.assertIs(first_client, second_client)
        gateway._create_client.assert_called_once_with(api_key="pinecone-api-key")  # pylint: disable=protected-access

        race_gateway, _ = _build_gateway(config=_make_config())
        race_gateway._client = None  # pylint: disable=protected-access

        class _InjectingClientLock:
            async def __aenter__(self_inner):  # noqa: ANN001
                race_gateway._client = "injected-client"  # pylint: disable=protected-access
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001
                return False

        race_gateway._client_lock = _InjectingClientLock()  # pylint: disable=protected-access
        self.assertEqual(
            await race_gateway._get_client(),  # pylint: disable=protected-access
            "injected-client",
        )

        gateway._client = SimpleNamespace(IndexAsyncio=AsyncMock(return_value="idx"))  # pylint: disable=protected-access
        built_index = await gateway._build_index()  # pylint: disable=protected-access
        self.assertEqual(built_index, "idx")

        gateway._client = SimpleNamespace(
            IndexAsyncio=Mock(side_effect=TypeError("keyword unsupported")),
        )  # pylint: disable=protected-access
        gateway._call_provider_method = AsyncMock(  # pylint: disable=protected-access
            side_effect=[TypeError("keyword unsupported"), "idx3"]
        )
        self.assertEqual(
            await gateway._build_index(),  # pylint: disable=protected-access
            "idx3",
        )
        self.assertEqual(
            gateway._call_provider_method.await_args_list[1].args[1],  # pylint: disable=protected-access
            "https://example-idx.svc.pinecone.io",
        )
        gateway._call_provider_method = PineconeKnowledgeGateway._call_provider_method  # type: ignore[method-assign]  # pylint: disable=protected-access

        gateway._client = SimpleNamespace(Index=Mock(return_value="idx2"))  # pylint: disable=protected-access
        built_index = await gateway._build_index()  # pylint: disable=protected-access
        self.assertEqual(built_index, "idx2")

        gateway._client = SimpleNamespace()  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "index factory is unavailable"):
            await gateway._build_index()  # pylint: disable=protected-access

        gateway._index = None  # pylint: disable=protected-access
        gateway._build_index = AsyncMock(return_value=object())  # pylint: disable=protected-access
        first_index = await gateway._get_index()  # pylint: disable=protected-access
        second_index = await gateway._get_index()  # pylint: disable=protected-access
        self.assertIs(first_index, second_index)
        gateway._build_index.assert_awaited_once_with()  # pylint: disable=protected-access

        race_index_gateway, _ = _build_gateway(config=_make_config())
        race_index_gateway._index = None  # pylint: disable=protected-access

        class _InjectingIndexLock:
            async def __aenter__(self_inner):  # noqa: ANN001
                race_index_gateway._index = "injected-index"  # pylint: disable=protected-access
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001
                return False

        race_index_gateway._index_lock = _InjectingIndexLock()  # pylint: disable=protected-access
        self.assertEqual(
            await race_index_gateway._get_index(),  # pylint: disable=protected-access
            "injected-index",
        )

        with patch(
            "mugen.core.gateway.knowledge.pinecone.SentenceTransformer"
        ) as transformer:
            built_encoder = gateway._build_encoder()  # pylint: disable=protected-access
        self.assertIs(built_encoder, transformer.return_value)
        transformer.assert_called_once_with(
            model_name_or_path="all-mpnet-base-v2",
            tokenizer_kwargs={"clean_up_tokenization_spaces": False},
            cache_folder="/tmp/hf",
        )

        gateway._encoder = None  # pylint: disable=protected-access
        gateway._build_encoder = Mock(return_value="encoder")  # pylint: disable=protected-access
        self.assertEqual(await gateway._get_encoder(), "encoder")  # pylint: disable=protected-access
        self.assertEqual(await gateway._get_encoder(), "encoder")  # pylint: disable=protected-access
        gateway._build_encoder.assert_called_once_with()  # pylint: disable=protected-access

        race_encoder_gateway, _ = _build_gateway(config=_make_config())
        race_encoder_gateway._encoder = None  # pylint: disable=protected-access

        class _InjectingEncoderLock:
            async def __aenter__(self_inner):  # noqa: ANN001
                race_encoder_gateway._encoder = "injected-encoder"  # pylint: disable=protected-access
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001
                return False

        race_encoder_gateway._encoder_lock = _InjectingEncoderLock()  # pylint: disable=protected-access
        self.assertEqual(
            await race_encoder_gateway._get_encoder(),  # pylint: disable=protected-access
            "injected-encoder",
        )

        encoder = Mock()
        gateway._get_encoder = AsyncMock(return_value=encoder)  # pylint: disable=protected-access
        encoder.encode.return_value = _VectorLike()
        self.assertEqual(await gateway._encode_search_term("a"), [0.1, 0.2])  # pylint: disable=protected-access
        encoder.encode.return_value = [0.5, 0.6]
        self.assertEqual(await gateway._encode_search_term("b"), [0.5, 0.6])  # pylint: disable=protected-access
        encoder.encode.return_value = _IterableVector()
        self.assertEqual(await gateway._encode_search_term("c"), [0.3, 0.4])  # pylint: disable=protected-access

    def test_normalization_helpers(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())

        self.assertEqual(
            gateway._normalize_optional_filter(" value "),  # pylint: disable=protected-access
            "value",
        )
        self.assertIsNone(
            gateway._normalize_optional_filter(1)  # pylint: disable=protected-access
        )
        self.assertIsNone(
            gateway._normalize_optional_filter(" ")  # pylint: disable=protected-access
        )

        with self.assertRaisesRegex(ValueError, "search_term must be a string"):
            gateway._normalize_search_term(1)  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, "search_term must be non-empty"):
            gateway._normalize_search_term("  ")  # pylint: disable=protected-access
        self.assertEqual(
            gateway._normalize_search_term(" ok "), "ok"
        )  # pylint: disable=protected-access

        parsed_tenant_id = gateway._normalize_tenant_id(  # pylint: disable=protected-access
            str(uuid.uuid4())
        )
        self.assertTrue(uuid.UUID(parsed_tenant_id))
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
            gateway._normalize_min_similarity(None)  # pylint: disable=protected-access
        )
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
            gateway._normalize_uuid_text(  # pylint: disable=protected-access
                1,
                field_name="tenant_id",
            )
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            gateway._normalize_uuid_text(  # pylint: disable=protected-access
                "",
                field_name="tenant_id",
            )
        with self.assertRaisesRegex(RuntimeError, "must be a UUID string"):
            gateway._normalize_uuid_text(  # pylint: disable=protected-access
                "bad-uuid",
                field_name="tenant_id",
            )

        self.assertEqual(
            gateway._coerce_optional_string(1), "1"
        )  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._coerce_optional_string("")
        )  # pylint: disable=protected-access
        self.assertIsNone(
            gateway._coerce_float(None)
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
            gateway._build_snippet(  # pylint: disable=protected-access
                title=None,
                body=None,
            )
        )

        gateway._search_metric = "cosine"  # pylint: disable=protected-access
        similarity, distance = gateway._normalize_similarity_distance(0.8)  # pylint: disable=protected-access
        self.assertEqual(similarity, 0.8)
        self.assertAlmostEqual(float(distance), 0.2)
        gateway._search_metric = "dotproduct"  # pylint: disable=protected-access
        self.assertEqual(
            gateway._normalize_similarity_distance(0.8),  # pylint: disable=protected-access
            (0.8, None),
        )
        self.assertEqual(
            gateway._normalize_similarity_distance(None),  # pylint: disable=protected-access
            (None, None),
        )
        gateway._search_metric = "custom"  # pylint: disable=protected-access
        self.assertEqual(
            gateway._normalize_similarity_distance(0.6),  # pylint: disable=protected-access
            (0.6, None),
        )
        gateway._search_metric = "euclidean"  # pylint: disable=protected-access
        self.assertEqual(
            gateway._normalize_similarity_distance(0.8),  # pylint: disable=protected-access
            (0.8, None),
        )

        query_filter = gateway._build_query_filter(  # pylint: disable=protected-access
            tenant_id=parsed_uuid,
            channel="web",
            locale="en",
            category="billing",
        )
        self.assertEqual(query_filter["tenant_id"], parsed_uuid)
        self.assertEqual(query_filter["channel"], "web")
        self.assertEqual(query_filter["locale"], "en")
        self.assertEqual(query_filter["category"], "billing")

        matches = gateway._extract_matches({"matches": [{"id": 1}]})  # pylint: disable=protected-access
        self.assertEqual(matches, [{"id": 1}])
        matches = gateway._extract_matches(  # pylint: disable=protected-access
            _QueryResultWithMatches([{"id": 2}])
        )
        self.assertEqual(matches, [{"id": 2}])
        matches = gateway._extract_matches(  # pylint: disable=protected-access
            _QueryResultWithModelDump([{"id": 3}])
        )
        self.assertEqual(matches, [{"id": 3}])
        model_dump_nonlist = SimpleNamespace(model_dump=lambda: {"matches": "bad"})
        self.assertEqual(
            gateway._extract_matches(model_dump_nonlist),  # pylint: disable=protected-access
            [],
        )
        model_dump_nondict = SimpleNamespace(model_dump=lambda: ["bad"])
        self.assertEqual(
            gateway._extract_matches(model_dump_nondict),  # pylint: disable=protected-access
            [],
        )
        matches = gateway._extract_matches(  # pylint: disable=protected-access
            _QueryResultWithToDict([{"id": 4}])
        )
        self.assertEqual(matches, [{"id": 4}])
        to_dict_nonlist = SimpleNamespace(to_dict=lambda: {"matches": "bad"})
        self.assertEqual(
            gateway._extract_matches(to_dict_nonlist),  # pylint: disable=protected-access
            [],
        )
        to_dict_nondict = SimpleNamespace(to_dict=lambda: ["bad"])
        self.assertEqual(
            gateway._extract_matches(to_dict_nondict),  # pylint: disable=protected-access
            [],
        )
        self.assertEqual(
            gateway._extract_matches("bad"), []  # pylint: disable=protected-access
        )

    def test_match_item_normalization_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config(metric="cosine"))
        payload = _payload()

        metadata, score = gateway._extract_match_parts(  # pylint: disable=protected-access
            {"metadata": payload, "score": 0.9}
        )
        self.assertEqual(metadata, payload)
        self.assertEqual(score, 0.9)

        metadata, score = gateway._extract_match_parts(  # pylint: disable=protected-access
            _MatchObject(metadata=payload, score=0.8)
        )
        self.assertEqual(metadata, payload)
        self.assertEqual(score, 0.8)

        metadata, score = gateway._extract_match_parts(  # pylint: disable=protected-access
            _MatchWithDict(payload={"metadata": payload, "score": 0.7})
        )
        self.assertEqual(metadata, payload)
        self.assertEqual(score, 0.7)

        metadata, score = gateway._extract_match_parts(  # pylint: disable=protected-access
            {"metadata": "bad-shape", "score": 0.6}
        )
        self.assertEqual(metadata, {})
        self.assertEqual(score, 0.6)

        metadata, score = gateway._extract_match_parts(  # pylint: disable=protected-access
            SimpleNamespace(score=0.5)
        )
        self.assertEqual(metadata, {})
        self.assertEqual(score, 0.5)

        metadata, score = gateway._extract_match_parts(  # pylint: disable=protected-access
            _MatchWithDict(payload=["bad-shape"])
        )
        self.assertEqual(metadata, {})
        self.assertIsNone(score)

        metadata, score = gateway._extract_match_parts(  # pylint: disable=protected-access
            _MatchWithDict(payload={"metadata": "bad-shape", "score": 0.4})
        )
        self.assertEqual(metadata, {})
        self.assertIsNone(score)

        with self.assertRaisesRegex(RuntimeError, "missing required key"):
            gateway._normalise_item(  # pylint: disable=protected-access
                metadata={"tenant_id": str(uuid.uuid4())},
                score_raw=0.9,
            )

        item = gateway._normalise_item(  # pylint: disable=protected-access
            metadata=payload,
            score_raw=0.85,
        )
        self.assertEqual(item["similarity"], 0.85)
        self.assertAlmostEqual(float(item["distance"]), 0.15)

        filtered = gateway._normalise_items(  # pylint: disable=protected-access
            query_result={"matches": [{"metadata": payload, "score": 0.4}]},
            min_similarity=0.5,
        )
        self.assertEqual(filtered, [])

        unfiltered = gateway._normalise_items(  # pylint: disable=protected-access
            query_result={"matches": [{"metadata": payload, "score": 0.8}]},
            min_similarity=0.5,
        )
        self.assertEqual(len(unfiltered), 1)

    async def test_query_index_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config(namespace="ns-1"))
        gateway._get_index = AsyncMock(return_value=SimpleNamespace())  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "query API is unavailable"):
            await gateway._query_index(  # pylint: disable=protected-access
                query_vector=[0.1, 0.2],
                query_filter={"tenant_id": str(uuid.uuid4())},
                top_k=3,
            )

        gateway._get_index = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(query=AsyncMock(return_value={"bad": "shape"}))
        )
        with self.assertRaisesRegex(RuntimeError, "invalid query payload"):
            await gateway._query_index(  # pylint: disable=protected-access
                query_vector=[0.1, 0.2],
                query_filter={"tenant_id": str(uuid.uuid4())},
                top_k=3,
            )

        query_mock = AsyncMock(return_value={"matches": []})
        gateway._get_index = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(query=query_mock)
        )
        await gateway._query_index(  # pylint: disable=protected-access
            query_vector=[0.1, 0.2],
            query_filter={"tenant_id": str(uuid.uuid4())},
            top_k=4,
        )
        self.assertEqual(query_mock.await_args.kwargs["namespace"], "ns-1")
        self.assertEqual(query_mock.await_args.kwargs["top_k"], 4)
        self.assertTrue(query_mock.await_args.kwargs["include_metadata"])
        self.assertFalse(query_mock.await_args.kwargs["include_values"])

        gateway_no_namespace, _ = _build_gateway(config=_make_config(namespace=""))
        query_result_with_matches_attr = _QueryResultWithMatches([])
        query_mock = AsyncMock(return_value=query_result_with_matches_attr)
        gateway_no_namespace._get_index = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(query=query_mock)
        )
        await gateway_no_namespace._query_index(  # pylint: disable=protected-access
            query_vector=[0.1, 0.2],
            query_filter={"tenant_id": str(uuid.uuid4())},
            top_k=2,
        )
        self.assertNotIn("namespace", query_mock.await_args.kwargs)

        query_mock = AsyncMock(return_value={"matches": [{"metadata": _payload(), "score": 0.9}]})
        gateway._get_index = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(query=query_mock)
        )
        query_result = await gateway._query_index(  # pylint: disable=protected-access
            query_vector=[0.1, 0.2],
            query_filter={"tenant_id": str(uuid.uuid4())},
            top_k=1,
        )
        self.assertEqual(len(query_result["matches"]), 1)

        gateway._get_index = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(query=AsyncMock(return_value=SimpleNamespace()))
        )
        with self.assertRaisesRegex(RuntimeError, "invalid query payload"):
            await gateway._query_index(  # pylint: disable=protected-access
                query_vector=[0.1, 0.2],
                query_filter={"tenant_id": str(uuid.uuid4())},
                top_k=1,
            )

    async def test_provider_method_and_timeout_helpers(self) -> None:
        gateway, _ = _build_gateway(config=_make_config())

        async def _async_method(value):
            return value

        def _sync_method(value):
            return value

        def _sync_returns_awaitable(value):
            async def _inner():
                return value

            return _inner()

        self.assertEqual(
            await gateway._call_provider_method(_async_method, "a"),  # pylint: disable=protected-access
            "a",
        )
        self.assertEqual(
            await gateway._call_provider_method(_sync_method, "b"),  # pylint: disable=protected-access
            "b",
        )
        self.assertEqual(
            await gateway._call_provider_method(  # pylint: disable=protected-access
                _sync_returns_awaitable,
                "c",
            ),
            "c",
        )

        self.assertEqual(
            await gateway._await_with_timeout(  # pylint: disable=protected-access
                _async_method("ok"),
                timeout_seconds=None,
            ),
            "ok",
        )

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
            patch("mugen.core.gateway.knowledge.pinecone.asyncio.sleep", sleep_mock),
            self.assertRaisesRegex(RuntimeError, "again"),
        ):
            await gateway._execute_with_retry(  # pylint: disable=protected-access
                operation="search",
                request_factory=AsyncMock(side_effect=RuntimeError("again")),
            )
        sleep_mock.assert_awaited()

        with patch("builtins.max", return_value=-1):
            self.assertIsNone(
                await gateway._execute_with_retry(  # pylint: disable=protected-access
                    operation="search",
                    request_factory=AsyncMock(),
                )
            )

        gateway._closed = True  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "is closed"):
            gateway._assert_open()  # pylint: disable=protected-access

        self.assertIsNone(await gateway.aclose())

        close_calls: list[str] = []
        gateway._closed = False  # pylint: disable=protected-access

        def _sync_close():
            close_calls.append("index-sync")
            return None

        async def _async_close():
            close_calls.append("client-async")
            return None

        gateway._index = SimpleNamespace(close=_sync_close)  # pylint: disable=protected-access
        gateway._client = SimpleNamespace(close=_async_close)  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())
        self.assertEqual(close_calls, ["index-sync", "client-async"])

        gateway._closed = False  # pylint: disable=protected-access
        gateway._index = None  # pylint: disable=protected-access
        gateway._client = None  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

    async def test_close_resource_handles_aclose_hook(self) -> None:
        close_calls: list[str] = []

        async def _aclose():
            close_calls.append("aclose")
            return None

        await PineconeKnowledgeGateway._close_resource(  # pylint: disable=protected-access
            SimpleNamespace(aclose=_aclose)
        )
        self.assertEqual(close_calls, ["aclose"])

        def _aclose_sync():
            close_calls.append("aclose-sync")
            return None

        await PineconeKnowledgeGateway._close_resource(  # pylint: disable=protected-access
            SimpleNamespace(aclose=_aclose_sync)
        )
        await PineconeKnowledgeGateway._close_resource(  # pylint: disable=protected-access
            object()
        )
        self.assertEqual(close_calls, ["aclose", "aclose-sync"])

    async def test_check_readiness_paths(self) -> None:
        gateway, _ = _build_gateway(config=_make_config(timeout_seconds=None))
        gateway._get_index = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(describe_index_stats=AsyncMock(return_value={}))
        )
        gateway._get_encoder = AsyncMock(return_value=object())  # pylint: disable=protected-access

        timeouts: list[float] = []

        async def _with_timeout(awaitable, *, timeout_seconds):
            timeouts.append(float(timeout_seconds))
            return await awaitable

        with patch.object(
            gateway,
            "_await_with_timeout",
            side_effect=_with_timeout,
        ):
            await gateway.check_readiness()
        self.assertEqual(timeouts, [5.0, 5.0, 5.0])

        gateway._api_timeout_seconds = 2.5  # pylint: disable=protected-access
        timeouts = []
        with patch.object(
            gateway,
            "_await_with_timeout",
            side_effect=_with_timeout,
        ):
            await gateway.check_readiness()
        self.assertEqual(timeouts, [2.5, 2.5, 2.5])

        gateway._get_index = AsyncMock(return_value=SimpleNamespace())  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "probe is unavailable"):
            await gateway.check_readiness()

        gateway._get_index = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(
                describe_index_stats=AsyncMock(side_effect=RuntimeError("probe failed"))
            )
        )
        with self.assertRaisesRegex(RuntimeError, "probe failed"):
            await gateway.check_readiness()

        gateway._get_index = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(describe_index_stats=AsyncMock(return_value={}))
        )
        gateway._get_encoder = AsyncMock(  # pylint: disable=protected-access
            side_effect=RuntimeError("encoder failed")
        )
        with self.assertRaisesRegex(RuntimeError, "encoder initialization failed"):
            await gateway.check_readiness()

    async def test_search_success_and_failure_paths(self) -> None:
        tenant_id = uuid.uuid4()
        payload = _payload(tenant_id=str(tenant_id))
        gateway, logger = _build_gateway(config=_make_config())
        gateway._encode_search_term = AsyncMock(return_value=[0.1, 0.2])  # pylint: disable=protected-access
        gateway._execute_with_retry = AsyncMock(  # pylint: disable=protected-access
            return_value={"matches": [{"metadata": payload, "score": 0.9}]}
        )

        result = await gateway.search(
            PineconeSearchVendorParams(
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
        self.assertEqual(result.raw_vendor["provider"], "pinecone")
        self.assertEqual(result.raw_vendor["metric"], "cosine")
        self.assertEqual(result.raw_vendor["top_k"], 5)
        self.assertEqual(result.raw_vendor["min_similarity"], 0.8)

        with self.assertRaisesRegex(ValueError, "search_term must be a string"):
            await gateway.search(
                PineconeSearchVendorParams(
                    search_term=123,  # type: ignore[arg-type]
                    tenant_id=tenant_id,
                )
            )

        gateway._execute_with_retry = AsyncMock(  # pylint: disable=protected-access
            side_effect=RuntimeError("transport")
        )
        with self.assertRaises(KnowledgeGatewayRuntimeError) as raised:
            await gateway.search(
                PineconeSearchVendorParams(
                    search_term="hello",
                    tenant_id=tenant_id,
                )
            )
        self.assertEqual(raised.exception.provider, "pinecone")
        self.assertEqual(raised.exception.operation, "search")
        logger.warning.assert_any_call(
            "PineconeKnowledgeGateway transport failure "
            "(operation=search error=RuntimeError: transport)"
        )


if __name__ == "__main__":
    unittest.main()
